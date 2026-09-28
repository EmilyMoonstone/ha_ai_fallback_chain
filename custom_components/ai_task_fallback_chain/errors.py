"""Error classification and cooldown calculation.

This module deliberately has no Home Assistant imports so it can be tested
without a Home Assistant installation.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
import re
from zoneinfo import ZoneInfo

# Google resets its per-day API quotas at midnight Pacific time.
QUOTA_RESET_TZ = ZoneInfo("America/Los_Angeles")

_QUOTA_RE = re.compile(
    r"\b429\b|resource_exhausted|rate[ _-]?limit|quota|too many requests",
    re.IGNORECASE,
)
_DAILY_RE = re.compile(r"per[ _-]?day", re.IGNORECASE)
_TRANSIENT_RE = re.compile(
    r"\b50[0234]\b|unavailable|overloaded|high demand|internal error"
    r"|bad gateway|deadline[ _]exceeded|try again later|connection reset"
    r"|server disconnected",
    re.IGNORECASE,
)


class ErrorKind(StrEnum):
    """What kind of failure a stage had."""

    DAILY_QUOTA = "daily_quota"
    """Quota per day exhausted (e.g. Gemini free tier requests per day)."""

    QUOTA = "quota"
    """Any other quota / rate limit error (HTTP 429)."""

    TRANSIENT = "transient"
    """Temporary server side problem (HTTP 5xx, model overloaded)."""

    TIMEOUT = "timeout"
    """The stage did not answer in time."""

    OTHER = "other"
    """Everything else."""

    @property
    def is_quota(self) -> bool:
        """Return True for quota/rate limit errors."""
        return self in (ErrorKind.QUOTA, ErrorKind.DAILY_QUOTA)

    @property
    def is_retryable(self) -> bool:
        """Return True if retrying the same stage right away makes sense."""
        return self is ErrorKind.TRANSIENT


def exception_text(err: BaseException) -> str:
    """Return the text of an exception including its causes."""
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = err
    while current is not None and id(current) not in seen and len(parts) < 10:
        seen.add(id(current))
        message = str(current)
        parts.append(
            f"{type(current).__name__}: {message}" if message else type(current).__name__
        )
        current = current.__cause__ or current.__context__
    return " <- ".join(parts)


def classify_error(err: BaseException) -> ErrorKind:
    """Classify an exception raised by a stage."""
    if isinstance(err, TimeoutError):
        return ErrorKind.TIMEOUT
    text = exception_text(err)
    if _QUOTA_RE.search(text):
        return ErrorKind.DAILY_QUOTA if _DAILY_RE.search(text) else ErrorKind.QUOTA
    if _TRANSIENT_RE.search(text):
        return ErrorKind.TRANSIENT
    return ErrorKind.OTHER


def next_quota_reset(now: datetime, tz: ZoneInfo = QUOTA_RESET_TZ) -> datetime:
    """Return the next midnight in the quota time zone, as UTC."""
    local = now.astimezone(tz)
    next_day = local.date() + timedelta(days=1)
    return datetime.combine(next_day, time(0, 0), tzinfo=tz).astimezone(UTC)


def cooldown_until(
    kind: ErrorKind,
    now: datetime,
    *,
    cooldown_error: timedelta,
    cooldown_quota: timedelta,
    daily_quota_until_reset: bool,
) -> datetime | None:
    """Return until when a failed stage should be skipped (None = not at all)."""
    if kind is ErrorKind.DAILY_QUOTA and daily_quota_until_reset:
        return next_quota_reset(now)
    delay = cooldown_quota if kind.is_quota else cooldown_error
    if delay <= timedelta(0):
        return None
    return now + delay


def shorten(text: str, max_length: int) -> str:
    """Shorten a text for logs, events and attributes."""
    text = " ".join(text.split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 1] + "…"
