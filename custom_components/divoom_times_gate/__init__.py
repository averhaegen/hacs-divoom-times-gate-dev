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
    DOMAIN,
)
from .coordinator import TimesGateCoordinator
from .device import TimesGate

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LIGHT, Platform.BUTTON]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Divoom Times Gate from a config entry."""
    session = async_get_clientsession(hass)
    device = TimesGate(
        entry.data[CONF_IP_ADDRESS],
        int(entry.data[CONF_LOCAL_TOKEN]),
        session,
    )

    if not await device.ping():
        raise ConfigEntryNotReady(f"Times Gate at {entry.data[CONF_IP_ADDRESS]} not reachable")

    interval = entry.data.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL)
    coordinator = TimesGateCoordinator(hass, device, interval)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
