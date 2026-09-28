"""Shared base for the entities of a fallback chain."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from .chain import AITaskFallbackChain
from .const import DOMAIN


class FallbackChainEntity(Entity):
    """Base entity, all entities of one chain share a service device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, key: str | None) -> None:
        """Initialize the entity."""
        self._entry = entry
        self._chain: AITaskFallbackChain = entry.runtime_data
        self._attr_unique_id = entry.entry_id if key is None else f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="AI Task Fallback Chain",
            model="Fallback-Kette",
            entry_type=DeviceEntryType.SERVICE,
        )
