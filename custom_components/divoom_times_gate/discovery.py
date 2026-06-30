"""LAN discovery of Divoom devices.

Divoom's cloud endpoint returns the devices that share the caller's public IP
(i.e. on the same LAN). This is the only cloud call the integration makes, and
only during setup — normal operation is fully local. It saves the user from
finding the device IP by hand; the per-device LocalToken still comes from the
Divoom app.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import aiohttp

_LOGGER = logging.getLogger(__name__)

_DISCOVERY_URL = "https://app.divoom-gz.com/Device/ReturnSameLANDevice"


@dataclass(frozen=True)
class DiscoveredDevice:
    name: str
    ip: str
    mac: str
    hardware: int


async def async_discover_devices(session: aiohttp.ClientSession) -> list[DiscoveredDevice]:
    """Return Divoom devices on the same LAN (best-effort; [] on failure)."""
    try:
        async with session.post(
            _DISCOVERY_URL, json={}, timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            data = await resp.json(content_type=None)
    except Exception as err:  # noqa: BLE001 - discovery is best-effort
        _LOGGER.debug("Divoom LAN discovery failed: %s", err)
        return []

    if data.get("ReturnCode") != 0:
        return []

    devices: list[DiscoveredDevice] = []
    for item in data.get("DeviceList", []):
        ip = item.get("DevicePrivateIP")
        if not ip:
            continue
        devices.append(
            DiscoveredDevice(
                name=item.get("DeviceName", "Divoom device"),
                ip=ip,
                mac=item.get("DeviceMac", ""),
                hardware=int(item.get("Hardware", 400)),
            )
        )
    return devices
