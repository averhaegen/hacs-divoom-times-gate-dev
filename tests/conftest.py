"""Shared pytest fixtures for the Divoom Times Gate integration."""
from __future__ import annotations

from collections.abc import Generator
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.divoom_times_gate.config_flow import DivoomTimesGateConfigFlow
from custom_components.divoom_times_gate.const import (
    CONF_DASHBOARD_BASE,
    CONF_DEVICE_ID,
    CONF_FACES,
    CONF_HARDWARE,
    CONF_IP_ADDRESS,
    CONF_LOCAL_TOKEN,
    CONF_MAC,
    CONF_REFRESH_INTERVAL,
    CONF_SCREENS,
    DEFAULT_HARDWARE,
    DEFAULT_REFRESH_INTERVAL,
    DOMAIN,
)
from custom_components.divoom_times_gate.defaults import DEFAULT_FACES, DEFAULT_SCREENS
from custom_components.divoom_times_gate.discovery import DiscoveredDevice


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow pytest-homeassistant-custom-component to load this repo's integration."""


@pytest.fixture(autouse=True)
def reset_discovery_cache() -> Generator[None]:
    """Clear the config flow's class-level discovery cache between tests.

    ``DivoomTimesGateConfigFlow._discovered`` is a mutable class attribute, so a
    discovery result from one test would otherwise leak into the next one.
    """
    DivoomTimesGateConfigFlow._discovered = []
    yield
    DivoomTimesGateConfigFlow._discovered = []


def make_discovered(
    name: str = "Times Gate",
    ip: str = "192.168.1.25",
    mac: str = "aa:bb:cc:dd:ee:ff",
    hardware: int = DEFAULT_HARDWARE,
    device_id: int = 4242,
) -> DiscoveredDevice:
    """Build a ``DiscoveredDevice`` with sensible per-test defaults."""
    return DiscoveredDevice(
        name=name, ip=ip, mac=mac, hardware=hardware, device_id=device_id
    )


@dataclass
class FakeTimesGate:
    """Network-free stand-in for ``TimesGate`` used by coordinator tests."""

    ip: str = "192.168.1.25"
    local_token: int = 123456
    hardware: int = DEFAULT_HARDWARE
    consecutive_failures: int = 0
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = field(default_factory=list)
    _pic_id: int = 0

    def _record(self, name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((name, args, kwargs))
        return {"error_code": 0}

    async def ping(self) -> bool:
        self._record("ping")
        return True

    async def get_conf(self) -> dict[str, Any]:
        return self._record("get_conf")

    async def reset_pic_counter(self) -> None:
        self._record("reset_pic_counter")

    async def set_brightness(self, brightness: int) -> dict[str, Any]:
        return self._record("set_brightness", brightness)

    async def turn_on(self) -> dict[str, Any]:
        return self._record("turn_on")

    async def turn_off(self) -> dict[str, Any]:
        return self._record("turn_off")

    async def send_jpeg(self, jpeg_bytes: bytes, screen: int) -> dict[str, Any]:
        return self._record("send_jpeg", jpeg_bytes, screen)

    async def send_item_list(
        self, screen: int, items: list[dict[str, Any]], background_gif: str | None = None
    ) -> dict[str, Any]:
        return self._record("send_item_list", screen, items, background_gif=background_gif)

    async def send_command_list(self, commands: list[dict[str, Any]]) -> dict[str, Any]:
        return self._record("send_command_list", commands)

    async def set_clock_face(
        self, screen: int, clock_id: int, independence_id: int | None = None
    ) -> dict[str, Any]:
        return self._record(
            "set_clock_face", screen, clock_id, independence_id=independence_id
        )

    async def set_visualizer(
        self, screen: int, eq_position: int, independence_id: int | None = None
    ) -> dict[str, Any]:
        return self._record(
            "set_visualizer", screen, eq_position, independence_id=independence_id
        )

    async def set_whole_face(self, clock_id: int) -> dict[str, Any]:
        return self._record("set_whole_face", clock_id)

    async def set_independent_preset(self, independence_id: int) -> dict[str, Any]:
        return self._record("set_independent_preset", independence_id)

    async def play_gif(self, screen: int, files: list[str]) -> dict[str, Any]:
        return self._record("play_gif", screen, files)

    async def send_animation(
        self, frames: list[bytes], screen: int, speed_ms: int = 200
    ) -> dict[str, Any]:
        return self._record("send_animation", frames, screen, speed_ms)

    # The coordinator batches a tick into one Draw/CommandList, so it calls the
    # build_* helpers far more often than the send_* ones. They stay pure: they
    # only shape a payload, so the fake returns the same dicts the real client
    # would, without recording a call.
    def build_jpeg(self, jpeg_bytes: bytes, screen: int) -> dict[str, Any]:
        self._pic_id += 1
        return {
            "Command": "Draw/SendHttpGif",
            "PicID": self._pic_id,
            "LcdArray": [1 if i == screen else 0 for i in range(5)],
        }

    def build_clock_face(
        self, screen: int, clock_id: int, independence_id: int | None = None
    ) -> dict[str, Any]:
        payload = {
            "Command": "Channel/SetClockSelectId",
            "ClockId": clock_id,
            "LcdIndex": screen,
        }
        if independence_id:
            payload["LcdIndependence"] = independence_id
        return payload

    def build_visualizer(
        self, screen: int, eq_position: int, independence_id: int | None = None
    ) -> dict[str, Any]:
        payload = {
            "Command": "Channel/SetEqPosition",
            "EqPosition": eq_position,
            "LcdIndex": screen,
        }
        if independence_id:
            payload["LcdIndependence"] = independence_id
        return payload

    def build_play_gif(self, screen: int, files: list[str]) -> dict[str, Any]:
        return {
            "Command": "Device/PlayGif",
            "FileName": files,
            "LcdArray": [1 if i == screen else 0 for i in range(5)],
        }

    def build_item_list(
        self, screen: int, items: list[dict[str, Any]], background_gif: str | None = None
    ) -> dict[str, Any]:
        payload = {
            "Command": "Draw/SendHttpItemList",
            "LcdIndex": screen,
            "ItemList": items,
            "NewFlag": 1 if background_gif else 0,
        }
        if background_gif:
            payload["BackgroudGif"] = background_gif
        return payload


@pytest.fixture
def fake_times_gate() -> FakeTimesGate:
    """Return a reusable fake device with the coordinator-facing TimesGate API."""
    return FakeTimesGate()


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a realistic config entry payload for this integration."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Times Gate (192.168.1.25)",
        unique_id="aa:bb:cc:dd:ee:ff",
        data={
            CONF_IP_ADDRESS: "192.168.1.25",
            CONF_LOCAL_TOKEN: 123456,
            CONF_HARDWARE: DEFAULT_HARDWARE,
            CONF_MAC: "aa:bb:cc:dd:ee:ff",
            CONF_DEVICE_ID: 4242,
            CONF_REFRESH_INTERVAL: DEFAULT_REFRESH_INTERVAL,
        },
        options={
            CONF_SCREENS: deepcopy(DEFAULT_SCREENS),
            CONF_FACES: deepcopy(DEFAULT_FACES),
            CONF_DASHBOARD_BASE: "",
            CONF_REFRESH_INTERVAL: DEFAULT_REFRESH_INTERVAL,
        },
    )
