"""Config flow for the AI Task Fallback Chain."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.ai_task import DOMAIN as AI_TASK_DOMAIN
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
)

from .const import (
    CONF_ADD_ANOTHER,
    CONF_COOLDOWN_ERROR,
    CONF_COOLDOWN_QUOTA,
    CONF_DAILY_QUOTA_UNTIL_RESET,
    CONF_ENTITY_ID,
    CONF_REDEFINE_STAGES,
    CONF_RETRIES,
    CONF_RETRY_DELAY,
    CONF_STAGES,
    CONF_TIMEOUT,
    DEFAULT_COOLDOWN_ERROR,
    DEFAULT_COOLDOWN_QUOTA,
    DEFAULT_DAILY_QUOTA_UNTIL_RESET,
    DEFAULT_NAME,
    DEFAULT_RETRIES,
    DEFAULT_RETRY_DELAY,
    DEFAULT_TIMEOUT,
    DOMAIN,
)

_SETTING_DEFAULTS: dict[str, Any] = {
    CONF_TIMEOUT: DEFAULT_TIMEOUT,
    CONF_RETRIES: DEFAULT_RETRIES,
    CONF_RETRY_DELAY: DEFAULT_RETRY_DELAY,
    CONF_COOLDOWN_ERROR: DEFAULT_COOLDOWN_ERROR,
    CONF_COOLDOWN_QUOTA: DEFAULT_COOLDOWN_QUOTA,
    CONF_DAILY_QUOTA_UNTIL_RESET: DEFAULT_DAILY_QUOTA_UNTIL_RESET,
}


def _number(minimum: float, maximum: float, unit: str) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            unit_of_measurement=unit,
            mode=NumberSelectorMode.BOX,
        )
    )


def _settings_schema(values: dict[str, Any], *, with_name: bool) -> dict[Any, Any]:
    """Return the schema fields of the general settings."""
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=values.get(CONF_NAME, DEFAULT_NAME))] = (
            TextSelector()
        )
    fields.update(
        {
            vol.Required(CONF_TIMEOUT, default=values[CONF_TIMEOUT]): _number(5, 600, "s"),
            vol.Required(CONF_RETRIES, default=values[CONF_RETRIES]): _number(0, 5, "×"),
            vol.Required(CONF_RETRY_DELAY, default=values[CONF_RETRY_DELAY]): _number(
                0, 60, "s"
            ),
            vol.Required(
                CONF_COOLDOWN_ERROR, default=values[CONF_COOLDOWN_ERROR]
            ): _number(0, 1440, "min"),
            vol.Required(
                CONF_COOLDOWN_QUOTA, default=values[CONF_COOLDOWN_QUOTA]
            ): _number(0, 1440, "min"),
            vol.Required(
                CONF_DAILY_QUOTA_UNTIL_RESET,
                default=values[CONF_DAILY_QUOTA_UNTIL_RESET],
            ): BooleanSelector(),
        }
    )
    return fields


def _clean_settings(user_input: dict[str, Any]) -> dict[str, Any]:
    """Store numbers as int, the number selector returns floats."""
    return {
        CONF_TIMEOUT: int(user_input[CONF_TIMEOUT]),
        CONF_RETRIES: int(user_input[CONF_RETRIES]),
        CONF_RETRY_DELAY: int(user_input[CONF_RETRY_DELAY]),
        CONF_COOLDOWN_ERROR: int(user_input[CONF_COOLDOWN_ERROR]),
        CONF_COOLDOWN_QUOTA: int(user_input[CONF_COOLDOWN_QUOTA]),
        CONF_DAILY_QUOTA_UNTIL_RESET: bool(user_input[CONF_DAILY_QUOTA_UNTIL_RESET]),
    }


def _chain_entities(hass: HomeAssistant) -> list[str]:
    """Entities of fallback chains; they must not be stages (endless loop)."""
    registry = er.async_get(hass)
    return [
        entry.entity_id
        for entry in registry.entities.values()
        if entry.platform == DOMAIN and entry.domain == AI_TASK_DOMAIN
    ]


def _stage_list(hass: HomeAssistant, stages: list[str]) -> str:
    """Markdown list of stages for the form description."""
    if not stages:
        return "–"
    lines = []
    for number, entity_id in enumerate(stages, start=1):
        state = hass.states.get(entity_id)
        name = state.name if state is not None else entity_id
        lines.append(f"{number}. **{name}** `{entity_id}`")
    return "\n".join(lines)


class _StageStepsMixin:
    """Shared stage steps of the config and the options flow."""

    hass: HomeAssistant
    _stages: list[str]
    _suggested_stages: list[str]

    def _stage_schema(self) -> vol.Schema:
        index = len(self._stages)
        suggested = (
            self._suggested_stages[index]
            if index < len(self._suggested_stages)
            else None
        )
        entity_key = (
            vol.Required(CONF_ENTITY_ID, description={"suggested_value": suggested})
            if suggested
            else vol.Required(CONF_ENTITY_ID)
        )
        return vol.Schema(
            {
                entity_key: EntitySelector(
                    EntitySelectorConfig(
                        domain=AI_TASK_DOMAIN,
                        exclude_entities=[*_chain_entities(self.hass), *self._stages],
                    )
                ),
                vol.Required(
                    CONF_ADD_ANOTHER,
                    default=index + 1 < len(self._suggested_stages),
                ): BooleanSelector(),
            }
        )

    def _handle_stage_input(self, user_input: dict[str, Any]) -> dict[str, str]:
        """Validate and store one stage. Returns form errors."""
        entity_id = user_input[CONF_ENTITY_ID]
        if entity_id in self._stages:
            return {CONF_ENTITY_ID: "duplicate_stage"}
        if entity_id in _chain_entities(self.hass):
            return {CONF_ENTITY_ID: "chain_as_stage"}
        self._stages.append(entity_id)
        return {}


class AITaskFallbackChainConfigFlow(_StageStepsMixin, ConfigFlow, domain=DOMAIN):
    """Set up a fallback chain."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._name = DEFAULT_NAME
        self._settings: dict[str, Any] = {}
        self._stages = []
        self._suggested_stages = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return AITaskFallbackChainOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """General settings."""
        if user_input is not None:
            self._name = user_input[CONF_NAME].strip() or DEFAULT_NAME
            self._settings = _clean_settings(user_input)
            return await self.async_step_stage()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(_settings_schema(_SETTING_DEFAULTS, with_name=True)),
        )

    async def async_step_stage(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add one stage."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._handle_stage_input(user_input)
            if not errors:
                if user_input[CONF_ADD_ANOTHER]:
                    return await self.async_step_stage()
                return self.async_create_entry(
                    title=self._name,
                    data={},
                    options={**self._settings, CONF_STAGES: self._stages},
                )

        return self.async_show_form(
            step_id="stage",
            data_schema=self._stage_schema(),
            errors=errors,
            description_placeholders={
                "number": str(len(self._stages) + 1),
                "stages": _stage_list(self.hass, self._stages),
            },
        )


class AITaskFallbackChainOptionsFlow(_StageStepsMixin, OptionsFlow):
    """Change the settings or the stages of a chain."""

    def __init__(self) -> None:
        """Initialize the options flow."""
        self._settings: dict[str, Any] = {}
        self._stages = []
        self._suggested_stages = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """General settings and whether the stages should be redefined."""
        options = dict(self.config_entry.options)
        current_stages = list(options.get(CONF_STAGES, []))

        if user_input is not None:
            self._settings = _clean_settings(user_input)
            if user_input[CONF_REDEFINE_STAGES]:
                self._suggested_stages = current_stages
                return await self.async_step_stage()
            return self.async_create_entry(
                data={**self._settings, CONF_STAGES: current_stages}
            )

        values = {**_SETTING_DEFAULTS, **options}
        schema = _settings_schema(values, with_name=False)
        schema[vol.Required(CONF_REDEFINE_STAGES, default=False)] = BooleanSelector()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            description_placeholders={
                "stages": _stage_list(self.hass, current_stages)
            },
        )

    async def async_step_stage(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Define the stages again, the old ones are suggested."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._handle_stage_input(user_input)
            if not errors:
                if user_input[CONF_ADD_ANOTHER]:
                    return await self.async_step_stage()
                return self.async_create_entry(
                    data={**self._settings, CONF_STAGES: self._stages}
                )

        return self.async_show_form(
            step_id="stage",
            data_schema=self._stage_schema(),
            errors=errors,
            description_placeholders={
                "number": str(len(self._stages) + 1),
                "stages": _stage_list(self.hass, self._stages),
            },
        )
