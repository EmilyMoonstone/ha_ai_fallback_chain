"""The fallback chain that forwards AI tasks to several AI Task entities."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any, Literal

from homeassistant.components.ai_task import (
    DOMAIN as AI_TASK_DOMAIN,
    AITaskEntity,
    AITaskEntityFeature,
    GenDataTask,
    GenDataTaskResult,
    GenImageTask,
    GenImageTaskResult,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, Context, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.chat_session import async_get_chat_session
from homeassistant.util import dt as dt_util

from .const import (
    CONF_COOLDOWN_ERROR,
    CONF_COOLDOWN_QUOTA,
    CONF_DAILY_QUOTA_UNTIL_RESET,
    CONF_RETRIES,
    CONF_RETRY_DELAY,
    CONF_STAGES,
    CONF_TIMEOUT,
    DEFAULT_COOLDOWN_ERROR,
    DEFAULT_COOLDOWN_QUOTA,
    DEFAULT_DAILY_QUOTA_UNTIL_RESET,
    DEFAULT_RETRIES,
    DEFAULT_RETRY_DELAY,
    DEFAULT_TIMEOUT,
    DOMAIN,
    EVENT_ALL_STAGES_FAILED,
    EVENT_STAGE_FAILED,
    MAX_ERROR_LENGTH,
)
from .errors import ErrorKind, classify_error, cooldown_until, exception_text, shorten

_LOGGER = logging.getLogger(__name__)

TaskType = Literal["data", "image"]


@dataclass(slots=True)
class ChainSettings:
    """Settings of one chain."""

    stages: list[str]
    timeout: float = DEFAULT_TIMEOUT
    retries: int = DEFAULT_RETRIES
    retry_delay: float = DEFAULT_RETRY_DELAY
    cooldown_error: timedelta = timedelta(minutes=DEFAULT_COOLDOWN_ERROR)
    cooldown_quota: timedelta = timedelta(minutes=DEFAULT_COOLDOWN_QUOTA)
    daily_quota_until_reset: bool = DEFAULT_DAILY_QUOTA_UNTIL_RESET

    @classmethod
    def from_options(cls, options: dict[str, Any]) -> ChainSettings:
        """Create the settings from config entry options."""
        return cls(
            stages=list(options.get(CONF_STAGES, [])),
            timeout=float(options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)),
            retries=int(options.get(CONF_RETRIES, DEFAULT_RETRIES)),
            retry_delay=float(options.get(CONF_RETRY_DELAY, DEFAULT_RETRY_DELAY)),
            cooldown_error=timedelta(
                minutes=float(options.get(CONF_COOLDOWN_ERROR, DEFAULT_COOLDOWN_ERROR))
            ),
            cooldown_quota=timedelta(
                minutes=float(options.get(CONF_COOLDOWN_QUOTA, DEFAULT_COOLDOWN_QUOTA))
            ),
            daily_quota_until_reset=bool(
                options.get(
                    CONF_DAILY_QUOTA_UNTIL_RESET, DEFAULT_DAILY_QUOTA_UNTIL_RESET
                )
            ),
        )


@dataclass(slots=True)
class StageStats:
    """Runtime statistics of one stage."""

    entity_id: str
    successes: int = 0
    failures: int = 0
    last_error: str | None = None
    last_error_kind: ErrorKind | None = None
    last_error_at: datetime | None = None
    cooldown_until: datetime | None = None

    def in_cooldown(self, now: datetime) -> bool:
        """Return True while the stage should be skipped."""
        return self.cooldown_until is not None and self.cooldown_until > now

    def as_dict(self, now: datetime) -> dict[str, Any]:
        """Return the stats for state attributes."""
        return {
            "entity_id": self.entity_id,
            "successes": self.successes,
            "failures": self.failures,
            "last_error": self.last_error,
            "last_error_kind": self.last_error_kind,
            "last_error_at": self.last_error_at.isoformat()
            if self.last_error_at
            else None,
            "paused_until": self.cooldown_until.isoformat()
            if self.in_cooldown(now) and self.cooldown_until
            else None,
        }


@dataclass(slots=True)
class _Failure:
    stage: int
    entity_id: str
    kind: ErrorKind
    message: str
    attempts: int = 1


class AITaskFallbackChain:
    """Forward AI tasks to the first stage that works."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the chain."""
        self.hass = hass
        self.entry = entry
        self.settings = ChainSettings.from_options(dict(entry.options))
        self.stats = [StageStats(entity_id) for entity_id in self.settings.stages]
        self.last_stage: int | None = None
        self.last_entity_id: str | None = None
        self.last_used_at: datetime | None = None
        self._listeners: list[CALLBACK_TYPE] = []
        self._pending: set[asyncio.Task[Any]] = set()

    # ------------------------------------------------------------------ state

    @callback
    def async_add_listener(self, update_callback: CALLBACK_TYPE) -> Callable[[], None]:
        """Register a callback that is called when the chain state changes."""
        self._listeners.append(update_callback)

        @callback
        def remove() -> None:
            self._listeners.remove(update_callback)

        return remove

    @callback
    def _async_notify(self) -> None:
        for update_callback in list(self._listeners):
            update_callback()

    @callback
    def async_shutdown(self) -> None:
        """Cancel calls that are still running (e.g. abandoned after a timeout)."""
        for call in list(self._pending):
            call.cancel()
        self._listeners.clear()

    @callback
    def async_reset_cooldowns(self) -> None:
        """Try every stage normally again."""
        for stats in self.stats:
            stats.cooldown_until = None
        _LOGGER.info("%s: all pauses were reset", self.entry.title)
        self._async_notify()

    # ------------------------------------------------------------- running

    async def async_generate_data(
        self, task: GenDataTask, context: Context | None
    ) -> GenDataTaskResult:
        """Run a generate data task along the chain."""
        return await self._async_run("data", task, context)

    async def async_generate_image(
        self, task: GenImageTask, context: Context | None
    ) -> GenImageTaskResult:
        """Run a generate image task along the chain."""
        return await self._async_run("image", task, context)

    def _ordered_stages(self, now: datetime) -> list[int]:
        """Return stage indexes: active stages first, paused ones as last resort."""
        active = [i for i, s in enumerate(self.stats) if not s.in_cooldown(now)]
        paused = [i for i, s in enumerate(self.stats) if s.in_cooldown(now)]
        return active + paused

    def _get_entity(self, entity_id: str) -> AITaskEntity | None:
        # The ai_task component is stored under a HassKey, which is a str.
        component = self.hass.data.get(AI_TASK_DOMAIN)
        if component is None:
            return None
        return component.get_entity(entity_id)

    async def _async_run(
        self,
        task_type: TaskType,
        task: GenDataTask | GenImageTask,
        context: Context | None,
    ) -> Any:
        if not self.stats:
            raise HomeAssistantError(f"{self.entry.title}: no stages configured")

        failures: list[_Failure] = []
        needs_attachments = bool(getattr(task, "attachments", None))
        required = (
            AITaskEntityFeature.GENERATE_IMAGE
            if task_type == "image"
            else AITaskEntityFeature.GENERATE_DATA
        )

        for index in self._ordered_stages(dt_util.utcnow()):
            stats = self.stats[index]
            number = index + 1
            entity = self._get_entity(stats.entity_id)

            if entity is None:
                failures.append(
                    _Failure(number, stats.entity_id, ErrorKind.OTHER, "entity not found")
                )
                continue
            if entity.platform is not None and entity.platform.platform_name == DOMAIN:
                failures.append(
                    _Failure(
                        number,
                        stats.entity_id,
                        ErrorKind.OTHER,
                        "a fallback chain cannot be a stage of a chain",
                    )
                )
                continue
            features = entity.supported_features
            if required not in features or (
                needs_attachments
                and AITaskEntityFeature.SUPPORT_ATTACHMENTS not in features
            ):
                # Not an error of the stage, it just can't do this task.
                _LOGGER.debug(
                    "Stage %s (%s) does not support this task, skipping",
                    number,
                    stats.entity_id,
                )
                continue

            result = await self._async_try_stage(
                index, entity, task_type, task, context, failures
            )
            if result is not None:
                return result

        self.hass.bus.async_fire(
            EVENT_ALL_STAGES_FAILED,
            {
                "task_name": task.name,
                "message": f"{self.entry.title}: all stages failed",
                "errors": [
                    {
                        "stage": f.stage,
                        "entity_id": f.entity_id,
                        "error_kind": f.kind,
                        "error": f.message,
                    }
                    for f in failures
                ],
            },
        )
        self._async_notify()
        summary = "; ".join(
            f"{f.stage} ({f.entity_id}): {f.message}" for f in failures
        ) or "no stage supports this task"
        raise HomeAssistantError(f"{self.entry.title}: all stages failed – {summary}")

    async def _async_try_stage(
        self,
        index: int,
        entity: AITaskEntity,
        task_type: TaskType,
        task: GenDataTask | GenImageTask,
        context: Context | None,
        failures: list[_Failure],
    ) -> Any:
        """Try one stage, with retries on transient errors. None = failed."""
        stats = self.stats[index]
        attempts = 1 + max(0, self.settings.retries)

        for attempt in range(1, attempts + 1):
            try:
                result = await self._async_call_with_timeout(
                    entity, task_type, task, context
                )
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - every error means "next stage"
                kind = classify_error(err)
                if kind.is_retryable and attempt < attempts:
                    delay = self.settings.retry_delay * attempt
                    _LOGGER.info(
                        "AI task stage %s (%s) temporarily unavailable, "
                        "retry %s/%s in %ss: %s",
                        index + 1,
                        stats.entity_id,
                        attempt,
                        attempts - 1,
                        delay,
                        shorten(exception_text(err), MAX_ERROR_LENGTH),
                    )
                    await asyncio.sleep(delay)
                    continue
                failures.append(self._record_failure(index, kind, err, attempt, task))
                return None

            self._record_success(index)
            return result
        return None

    async def _async_call_with_timeout(
        self,
        entity: AITaskEntity,
        task_type: TaskType,
        task: GenDataTask | GenImageTask,
        context: Context | None,
    ) -> Any:
        """Run the stage, but give up after the timeout no matter what.

        The call runs in its own task. If the stage does not react to being
        cancelled quickly (e.g. because a client library retries internally),
        the chain still continues with the next stage right after the timeout
        instead of waiting for the stage to give up by itself.
        """
        call = asyncio.create_task(
            self._async_call(entity, task_type, task, context),
            name=f"{DOMAIN} {entity.entity_id}",
        )
        self._pending.add(call)
        call.add_done_callback(self._async_call_done)
        try:
            done, _ = await asyncio.wait({call}, timeout=self.settings.timeout)
        except asyncio.CancelledError:
            call.cancel()
            raise
        if call not in done:
            call.cancel()
            raise TimeoutError(
                f"no answer within {self.settings.timeout:g} s"
            )
        return call.result()

    def _async_call_done(self, call: asyncio.Task[Any]) -> None:
        """Forget a finished call and swallow errors of abandoned calls."""
        self._pending.discard(call)
        if not call.cancelled():
            call.exception()  # mark as retrieved, avoids "never retrieved" logs

    async def _async_call(
        self,
        entity: AITaskEntity,
        task_type: TaskType,
        task: GenDataTask | GenImageTask,
        context: Context | None,
    ) -> Any:
        """Run the task on one stage in its own chat session."""
        with async_get_chat_session(self.hass) as session:
            if task_type == "image":
                assert isinstance(task, GenImageTask)
                return await entity.internal_async_generate_image(
                    session, task, context=context
                )
            assert isinstance(task, GenDataTask)
            return await entity.internal_async_generate_data(
                session, task, context=context
            )

    # ------------------------------------------------------------ bookkeeping

    @callback
    def _record_success(self, index: int) -> None:
        stats = self.stats[index]
        stats.successes += 1
        stats.cooldown_until = None
        self.last_stage = index + 1
        self.last_entity_id = stats.entity_id
        self.last_used_at = dt_util.utcnow()
        if index > 0:
            _LOGGER.debug("AI task answered by stage %s (%s)", index + 1, stats.entity_id)
        self._async_notify()

    @callback
    def _record_failure(
        self,
        index: int,
        kind: ErrorKind,
        err: BaseException,
        attempts: int,
        task: GenDataTask | GenImageTask,
    ) -> _Failure:
        stats = self.stats[index]
        now = dt_util.utcnow()
        message = "Timeout" if kind is ErrorKind.TIMEOUT else exception_text(err)
        message = shorten(message, MAX_ERROR_LENGTH)
        until = cooldown_until(
            kind,
            now,
            cooldown_error=self.settings.cooldown_error,
            cooldown_quota=self.settings.cooldown_quota,
            daily_quota_until_reset=self.settings.daily_quota_until_reset,
        )

        stats.failures += 1
        stats.last_error = message
        stats.last_error_kind = kind
        stats.last_error_at = now
        stats.cooldown_until = until

        if until is None:
            pause = "not pausing it"
        else:
            pause = (
                f"skipping it until {dt_util.as_local(until).isoformat(timespec='minutes')}"
            )
        _LOGGER.warning(
            "AI task stage %s (%s) failed (%s%s): %s -> trying next stage, %s",
            index + 1,
            stats.entity_id,
            kind,
            f", after {attempts} attempts" if attempts > 1 else "",
            message,
            pause,
        )
        self.hass.bus.async_fire(
            EVENT_STAGE_FAILED,
            {
                "stage": index + 1,
                "entity_id": stats.entity_id,
                "task_name": task.name,
                "error": message,
                "error_kind": kind,
                "quota_error": kind.is_quota,
                "attempts": attempts,
                "cooldown_until": until.isoformat() if until else None,
                "message": f"{self.entry.title}: stage {index + 1} "
                f"({stats.entity_id}) failed",
            },
        )
        self._async_notify()
        return _Failure(index + 1, stats.entity_id, kind, message, attempts)

    @callback
    def stage_attributes(self) -> list[dict[str, Any]]:
        """Return the stats of all stages for state attributes."""
        now = dt_util.utcnow()
        return [
            {"stage": i + 1, **s.as_dict(now)} for i, s in enumerate(self.stats)
        ]
