"""The Divoom Times Gate integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_IP_ADDRESS,
    CONF_LOCAL_TOKEN,
    CONF_REFRESH_INTERVAL,
    DEFAULT_REFRESH_INTERVAL,
)
from .coordinator import TimesGateCoordinator
from .device import TimesGate

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.BUTTON]

type DivoomTimesGateConfigEntry = ConfigEntry[TimesGateCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: DivoomTimesGateConfigEntry
) -> bool:
    """Set up Divoom Times Gate from a config entry."""
    session = async_get_clientsession(hass)
    device = TimesGate(
        entry.data[CONF_IP_ADDRESS],
        int(entry.data[CONF_LOCAL_TOKEN]),
        session,
    )

    if not await device.ping():
        raise ConfigEntryNotReady(
            f"Times Gate at {entry.data[CONF_IP_ADDRESS]} not reachable"
        )

    interval: int = entry.options.get(
        CONF_REFRESH_INTERVAL,
        entry.data.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL),
    )
    coordinator = TimesGateCoordinator(hass, entry, device, interval)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(
    hass: HomeAssistant, entry: DivoomTimesGateConfigEntry
) -> None:
    """Reload the entry when options change so new screens take effect."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: DivoomTimesGateConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
