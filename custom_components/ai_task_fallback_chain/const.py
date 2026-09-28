"""Constants for the AI Task Fallback Chain integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "ai_task_fallback_chain"

CONF_STAGES: Final = "stages"
CONF_ENTITY_ID: Final = "entity_id"
CONF_TIMEOUT: Final = "timeout"
CONF_RETRIES: Final = "retries"
CONF_RETRY_DELAY: Final = "retry_delay"
CONF_COOLDOWN_ERROR: Final = "cooldown_error"
CONF_COOLDOWN_QUOTA: Final = "cooldown_quota"
CONF_DAILY_QUOTA_UNTIL_RESET: Final = "daily_quota_until_reset"
CONF_ADD_ANOTHER: Final = "add_another"
CONF_REDEFINE_STAGES: Final = "redefine_stages"

DEFAULT_NAME: Final = "AI Task Fallback-Kette"
DEFAULT_TIMEOUT: Final = 60  # seconds per attempt; LLMs are slower than TTS
DEFAULT_RETRIES: Final = 2  # extra attempts on the same stage after 5xx/overload
DEFAULT_RETRY_DELAY: Final = 3  # seconds, grows linearly per attempt
DEFAULT_COOLDOWN_ERROR: Final = 5  # minutes
DEFAULT_COOLDOWN_QUOTA: Final = 60  # minutes
DEFAULT_DAILY_QUOTA_UNTIL_RESET: Final = True

EVENT_STAGE_FAILED: Final = f"{DOMAIN}_stage_failed"
EVENT_ALL_STAGES_FAILED: Final = f"{DOMAIN}_all_stages_failed"

MAX_ERROR_LENGTH: Final = 300
