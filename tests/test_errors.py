"""Tests for the error classification (no Home Assistant needed)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys
import unittest

# Load errors.py directly, the package __init__ needs Home Assistant.
_PATH = (
    Path(__file__).parent.parent
    / "custom_components"
    / "ai_task_fallback_chain"
    / "errors.py"
)
_SPEC = importlib.util.spec_from_file_location("chain_errors", _PATH)
errors = importlib.util.module_from_spec(_SPEC)
sys.modules["chain_errors"] = errors
_SPEC.loader.exec_module(errors)

ErrorKind = errors.ErrorKind

GEMINI_503 = (
    "Sorry, I had a problem getting a response from Google Generative AI.: {\n"
    '  "error": {\n    "code": 503,\n'
    '    "message": "This model is currently experiencing high demand. Spikes in '
    'demand are usually temporary. Please try again later.",\n'
    '    "status": "UNAVAILABLE"\n  }\n}'
)
GEMINI_429_DAY = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded "
    "your current quota', 'details': [{'quotaId': "
    "'GenerateRequestsPerDayPerProjectPerModel-FreeTier', 'quotaValue': '10'}]}}"
)
GEMINI_429_MINUTE = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'details': [{'quotaId': "
    "'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}]}}"
)


class HomeAssistantError(Exception):
    """Stand-in for homeassistant.exceptions.HomeAssistantError."""


class ClassifyTest(unittest.TestCase):
    """classify_error."""

    def test_gemini_overloaded_is_transient(self) -> None:
        kind = errors.classify_error(HomeAssistantError(GEMINI_503))
        self.assertIs(kind, ErrorKind.TRANSIENT)
        self.assertTrue(kind.is_retryable)
        self.assertFalse(kind.is_quota)

    def test_daily_quota(self) -> None:
        kind = errors.classify_error(HomeAssistantError(GEMINI_429_DAY))
        self.assertIs(kind, ErrorKind.DAILY_QUOTA)
        self.assertTrue(kind.is_quota)
        self.assertFalse(kind.is_retryable)

    def test_minute_quota(self) -> None:
        kind = errors.classify_error(HomeAssistantError(GEMINI_429_MINUTE))
        self.assertIs(kind, ErrorKind.QUOTA)

    def test_quota_found_in_cause(self) -> None:
        try:
            try:
                raise RuntimeError(GEMINI_429_DAY)
            except RuntimeError as inner:
                raise HomeAssistantError("Error during AI task") from inner
        except HomeAssistantError as err:
            self.assertIs(errors.classify_error(err), ErrorKind.DAILY_QUOTA)

    def test_timeout(self) -> None:
        self.assertIs(errors.classify_error(TimeoutError()), ErrorKind.TIMEOUT)

    def test_other(self) -> None:
        kind = errors.classify_error(HomeAssistantError("Invalid API key"))
        self.assertIs(kind, ErrorKind.OTHER)

    def test_numbers_in_text_are_not_status_codes(self) -> None:
        kind = errors.classify_error(ValueError("expected 15030 tokens"))
        self.assertIs(kind, ErrorKind.OTHER)


class CooldownTest(unittest.TestCase):
    """cooldown_until and next_quota_reset."""

    settings = {
        "cooldown_error": timedelta(minutes=5),
        "cooldown_quota": timedelta(minutes=60),
        "daily_quota_until_reset": True,
    }

    def test_reset_summer(self) -> None:
        # 28.09.2026 13:40 UTC = 06:40 PDT -> reset 29.09. 00:00 PDT = 07:00 UTC
        now = datetime(2026, 9, 28, 13, 40, tzinfo=UTC)
        self.assertEqual(
            errors.next_quota_reset(now), datetime(2026, 9, 29, 7, 0, tzinfo=UTC)
        )

    def test_reset_winter_evening(self) -> None:
        # 10.01.2027 09:00 UTC = 01:00 PST -> reset 11.01. 00:00 PST = 08:00 UTC
        now = datetime(2027, 1, 10, 9, 0, tzinfo=UTC)
        self.assertEqual(
            errors.next_quota_reset(now), datetime(2027, 1, 11, 8, 0, tzinfo=UTC)
        )

    def test_daily_quota_until_reset(self) -> None:
        now = datetime(2026, 9, 28, 13, 40, tzinfo=UTC)
        until = errors.cooldown_until(ErrorKind.DAILY_QUOTA, now, **self.settings)
        self.assertEqual(until, datetime(2026, 9, 29, 7, 0, tzinfo=UTC))

    def test_daily_quota_without_reset_option(self) -> None:
        now = datetime(2026, 9, 28, 13, 40, tzinfo=UTC)
        until = errors.cooldown_until(
            ErrorKind.DAILY_QUOTA,
            now,
            **{**self.settings, "daily_quota_until_reset": False},
        )
        self.assertEqual(until, now + timedelta(minutes=60))

    def test_transient_uses_error_pause(self) -> None:
        now = datetime(2026, 9, 28, 13, 40, tzinfo=UTC)
        until = errors.cooldown_until(ErrorKind.TRANSIENT, now, **self.settings)
        self.assertEqual(until, now + timedelta(minutes=5))

    def test_zero_means_never_skip(self) -> None:
        now = datetime(2026, 9, 28, 13, 40, tzinfo=UTC)
        until = errors.cooldown_until(
            ErrorKind.OTHER, now, **{**self.settings, "cooldown_error": timedelta(0)}
        )
        self.assertIsNone(until)


class ShortenTest(unittest.TestCase):
    """shorten."""

    def test_shorten(self) -> None:
        self.assertEqual(errors.shorten("a  b\n c", 10), "a b c")
        self.assertEqual(len(errors.shorten("x" * 50, 10)), 10)


if __name__ == "__main__":
    unittest.main()
