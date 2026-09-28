"""Button to reset all pauses of the chain."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import FallbackChainEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the button."""
    async_add_entities([ResetCooldownsButton(entry)])


class ResetCooldownsButton(FallbackChainEntity, ButtonEntity):
    """Try every stage normally again."""

    _attr_translation_key = "reset_cooldowns"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the button."""
        super().__init__(entry, "reset_cooldowns")

    async def async_press(self) -> None:
        """Reset the pauses."""
        self._chain.async_reset_cooldowns()
