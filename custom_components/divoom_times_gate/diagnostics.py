"""Diagnostics support for Divoom Times Gate."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import DivoomTimesGateConfigEntry
from .const import CONF_DISPDATA_SECRET, CONF_LOCAL_TOKEN, CONF_MAC

# The dispdata secret guards the unauthenticated HTTP views (any allowed
# entity's state is readable with it), so it must never leave the box in a
# shared diagnostics dump; the LocalToken is the device credential; the MAC
# is identifying info.
TO_REDACT = {CONF_LOCAL_TOKEN, CONF_DISPDATA_SECRET, CONF_MAC}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DivoomTimesGateConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry, with the LocalToken redacted."""
    coordinator = entry.runtime_data
    return {
        "entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "device_conf": await coordinator.device.get_conf(),
        "last_screen_results": coordinator.data,
        "last_update_success": coordinator.last_update_success,
    }
