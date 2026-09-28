"""Sensor showing which stage answered last."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import FallbackChainEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensor."""
    async_add_entities([LastStageSensor(entry)])


class LastStageSensor(FallbackChainEntity, SensorEntity):
    """Name of the AI Task entity that answered last."""

    _attr_translation_key = "last_stage"

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(entry, "last_stage")

    async def async_added_to_hass(self) -> None:
        """Register for updates of the chain."""
        await super().async_added_to_hass()
        self.async_on_remove(self._chain.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        """Return the friendly name of the stage that answered last."""
        if (entity_id := self._chain.last_entity_id) is None:
            return None
        if (state := self.hass.states.get(entity_id)) is not None:
            return state.name
        return entity_id

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the statistics of all stages."""
        chain = self._chain
        return {
            "stage": chain.last_stage,
            "entity_id": chain.last_entity_id,
            "last_used": chain.last_used_at.isoformat() if chain.last_used_at else None,
            "stages": chain.stage_attributes(),
        }
