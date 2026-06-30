"""LAN discovery + cloud reads for Divoom devices.

Divoom's cloud endpoint returns the devices that share the caller's public IP
(i.e. on the same LAN). These cloud calls happen only at setup / option build;
normal operation is fully local. They save the user from finding the device IP
by hand and let us read the device's native faces.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import aiohttp

_LOGGER = logging.getLogger(__name__)

_DISCOVERY_URL = "https://app.divoom-gz.com/Device/ReturnSameLANDevice"
_LCD_INFO_URL = "https://app.divoom-gz.com/Channel/Get5LcdInfoV2"
_WHOLE_LIST_URL = "https://app.divoom-gz.com/Channel/Get5LcdClockListForCommon"


@dataclass(frozen=True)
class DiscoveredDevice:
    name: str
    ip: str
    mac: str
    hardware: int
    device_id: int


@dataclass
class IndependentPreset:
    """One "Independent Display" preset (ControlN)."""

    name: str  # IndependenceName, e.g. "Control1"
    independence_id: int
    position: int  # LcdIndependPos 0-4 (stable slot)
    screen_clock_ids: list[int] = field(default_factory=list)


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
                device_id=int(item.get("DeviceId", 0)),
            )
        )
    return devices


async def async_get_independent_presets(
    session: aiohttp.ClientSession, device_id: int
) -> list[IndependentPreset]:
    """Return the device's Independent Display presets (Control1..5)."""
    if not device_id:
        return []
    try:
        async with session.post(
            _LCD_INFO_URL,
            json={"DeviceId": device_id, "DeviceType": "LCD"},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            data = await resp.json(content_type=None)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Get5LcdInfoV2 failed: %s", err)
        return []

    if data.get("ReturnCode") != 0:
        return []

    presets: list[IndependentPreset] = []
    for grp in data.get("LcdIndependenceList", []):
        presets.append(
            IndependentPreset(
                name=grp.get("IndependenceName", "Control"),
                independence_id=int(grp.get("LcdIndependence", 0)),
                position=int(grp.get("LcdIndependPos", 0)),
                screen_clock_ids=[s.get("LcdClockId", 0) for s in grp.get("LcdList", [])],
            )
        )
    presets.sort(key=lambda p: p.position)
    return presets


async def async_get_whole_faces(
    session: aiohttp.ClientSession, device_id: int, pages: int = 2
) -> dict[int, str]:
    """Return {clock_id: name} of whole-device (Overall Display) faces."""
    out: dict[int, str] = {}
    if not device_id:
        return out
    for page in range(1, pages + 1):
        try:
            async with session.post(
                _WHOLE_LIST_URL,
                json={"DeviceId": device_id, "Page": page},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json(content_type=None)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Get5LcdClockListForCommon failed: %s", err)
            break
        if data.get("ReturnCode") != 0:
            break
        for c in data.get("ClockList", []):
            out[int(c["ClockId"])] = c.get("ClockName", str(c["ClockId"]))
    return out
