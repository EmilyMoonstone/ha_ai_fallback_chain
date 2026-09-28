"""AI Task entity of the fallback chain."""

from __future__ import annotations

from dataclasses import replace

from homeassistant.components.ai_task import (
    AITaskEntity,
    AITaskEntityFeature,
    GenDataTask,
    GenDataTaskResult,
    GenImageTask,
    GenImageTaskResult,
)
from homeassistant.components.conversation import ChatLog
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import FallbackChainEntity

# Features the chain can pass on. The chain offers the union of its stages.
_FORWARDED_FEATURES = (
    AITaskEntityFeature.GENERATE_DATA
    | AITaskEntityFeature.SUPPORT_ATTACHMENTS
    | AITaskEntityFeature.GENERATE_IMAGE
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the AI Task entity."""
    async_add_entities([FallbackChainAITaskEntity(hass, entry)])


def _stage_features(hass: HomeAssistant, stages: list[str]) -> AITaskEntityFeature:
    """Union of the features of all stages, taken from the entity registry.

    The registry is used because the stage entities may not be loaded yet when
    the chain starts. Generating data is always offered.
    """
    registry = er.async_get(hass)
    features = AITaskEntityFeature.GENERATE_DATA
    for entity_id in stages:
        if (reg_entry := registry.async_get(entity_id)) is not None:
            features |= AITaskEntityFeature(reg_entry.supported_features or 0)
    return features & _FORWARDED_FEATURES


class FallbackChainAITaskEntity(FallbackChainEntity, AITaskEntity):
    """An AI Task entity that forwards every task along the chain."""

    _attr_name = None  # the entity is named like the chain

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the entity."""
        super().__init__(entry, None)
        self._attr_supported_features = _stage_features(hass, self._chain.settings.stages)

    async def _async_generate_data(
        self, task: GenDataTask, chat_log: ChatLog
    ) -> GenDataTaskResult:
        """Forward a generate data task."""
        result = await self._chain.async_generate_data(task, self._context)
        return replace(result, conversation_id=chat_log.conversation_id)

    async def _async_generate_image(
        self, task: GenImageTask, chat_log: ChatLog
    ) -> GenImageTaskResult:
        """Forward a generate image task."""
        result = await self._chain.async_generate_image(task, self._context)
        return replace(result, conversation_id=chat_log.conversation_id)
