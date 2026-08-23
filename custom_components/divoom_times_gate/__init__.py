"""The Divoom Times Gate integration."""
from __future__ import annotations

import logging
import secrets as secrets_module

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import (
    AUTH_INVALID,
    AUTH_OK,
    CONF_DEVICE_ID,
    CONF_DISPDATA_SECRET,
    CONF_HARDWARE,
    CONF_IP_ADDRESS,
    CONF_LOCAL_TOKEN,
    CONF_MAC,
    CONF_REFRESH_INTERVAL,
    DEFAULT_HARDWARE,
    DEFAULT_REFRESH_INTERVAL,
)
from .coordinator import TimesGateCoordinator
from .device import TimesGate
from .discovery import async_discover_devices, async_get_independent_presets
from .dispdata import register_secret, unregister_secret
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LIGHT, Platform.BUTTON, Platform.IMAGE, Platform.SELECT, Platform.SWITCH]

type DivoomTimesGateConfigEntry = ConfigEntry[TimesGateCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's service actions.

    Registering here rather than in async_setup_entry means the actions stay
    visible in the UI and in scripts even while every config entry is
    unloaded, so an automation referring to one fails with a clear error
    instead of "action not found".
    """
    async_register_services(hass)
    return True


async def _try_heal_ip(hass, entry, session) -> TimesGate | None:
    """If the device moved to a new IP, update the entry and return a client.

    Matches the cloud LAN discovery on MAC (or DeviceId as fallback). Returns
    a TimesGate client on the new IP, or None when nothing better was found.
    """
    mac = entry.data.get(CONF_MAC, "")
    device_id = int(entry.data.get(CONF_DEVICE_ID, 0))
    current_ip = entry.data[CONF_IP_ADDRESS]
    match = None
    for found in await async_discover_devices(session):
        if (mac and found.mac == mac) or (device_id and found.device_id == device_id):
            match = found
            break
    if match is None or match.ip == current_ip:
        return None
    _LOGGER.warning(
        "Times Gate moved from %s to %s — updating the config entry",
        current_ip,
        match.ip,
    )
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            CONF_IP_ADDRESS: match.ip,
            CONF_DEVICE_ID: match.device_id,
        },
        # The title usually embeds the IP ("Times Gate (192.168.x.x)").
        title=entry.title.replace(current_ip, match.ip),
    )
    return TimesGate(
        match.ip,
        int(entry.data[CONF_LOCAL_TOKEN]),
        session,
        entry.data.get(CONF_HARDWARE, DEFAULT_HARDWARE),
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: DivoomTimesGateConfigEntry
) -> bool:
    """Set up Divoom Times Gate from a config entry."""
    session = async_get_clientsession(hass)
    device = TimesGate(
        entry.data[CONF_IP_ADDRESS],
        int(entry.data[CONF_LOCAL_TOKEN]),
        session,
        entry.data.get(CONF_HARDWARE, DEFAULT_HARDWARE),
    )

    status = await device.check_auth()
    if status == AUTH_INVALID:
        # The device answered and refused the token, so its address is fine
        # and IP self-healing has nothing to fix. Ask the user for a fresh
        # LocalToken instead (they re-paired in the Divoom app).
        raise ConfigEntryAuthFailed(
            f"Times Gate at {entry.data[CONF_IP_ADDRESS]} rejected the LocalToken"
        )
    if status != AUTH_OK:
        # Nothing answered. The device may have moved to a new DHCP lease
        # while HA was down: re-run cloud LAN discovery, match on MAC (or
        # DeviceId), and retry there.
        device = await _try_heal_ip(hass, entry, session) or device
        status = await device.check_auth()
        if status == AUTH_INVALID:
            raise ConfigEntryAuthFailed(
                f"Times Gate at {entry.data[CONF_IP_ADDRESS]} rejected the LocalToken"
            )
        if status != AUTH_OK:
            raise ConfigEntryNotReady(
                f"Times Gate at {entry.data[CONF_IP_ADDRESS]} not reachable"
            )

    interval: int = entry.options.get(
        CONF_REFRESH_INTERVAL,
        entry.data.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL),
    )
    coordinator = TimesGateCoordinator(hass, entry, device, interval)

    # Resolve the DeviceId (needed for cloud reads). Older entries may not have
    # it stored, so fall back to discovering it by IP.
    device_id = int(entry.data.get(CONF_DEVICE_ID, 0))
    if not device_id:
        ip = entry.data[CONF_IP_ADDRESS]
        for found in await async_discover_devices(session):
            if found.ip == ip:
                device_id = found.device_id
                hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_DEVICE_ID: device_id}
                )
                break

    # Best-effort: load the device's Independent Display presets (cloud) so the
    # Display source select can offer them. Failure is non-fatal.
    coordinator.presets = await async_get_independent_presets(session, device_id)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # Generate a stable per-entry secret once, for the type-23 DispData poll
    # endpoint (see dispdata.py / docs/DISPDATA.md).
    dispdata_secret = entry.data.get(CONF_DISPDATA_SECRET)
    if not dispdata_secret:
        dispdata_secret = secrets_module.token_urlsafe(16)
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_DISPDATA_SECRET: dispdata_secret}
        )
    register_secret(hass, dispdata_secret)
    entry.async_on_unload(lambda: unregister_secret(hass, dispdata_secret))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    # Push each Select's restored state (see select.py's restore_display/
    # restore_screen) as a background task, not awaited here: platform setup
    # above already restored all in-memory state, but the actual device I/O
    # is deferred so a slow/unreachable device can't delay
    # async_setup_entry/HA startup. Best-effort — errors are logged, not raised.
    entry.async_create_background_task(
        hass,
        coordinator.async_apply_restored_state(),
        name="divoom_times_gate_apply_restored_state",
    )
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
