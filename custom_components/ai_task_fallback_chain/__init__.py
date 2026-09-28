"""AI Task Fallback Chain: forward AI tasks to the first AI Task entity that works."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .chain import AITaskFallbackChain

PLATFORMS: list[Platform] = [Platform.AI_TASK, Platform.SENSOR, Platform.BUTTON]

type FallbackChainConfigEntry = ConfigEntry[AITaskFallbackChain]


async def async_setup_entry(hass: HomeAssistant, entry: FallbackChainConfigEntry) -> bool:
    """Set up a fallback chain from a config entry."""
    chain = AITaskFallbackChain(hass, entry)
    entry.runtime_data = chain
    entry.async_on_unload(chain.async_shutdown)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: FallbackChainConfigEntry
) -> None:
    """Reload the chain when the options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: FallbackChainConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
