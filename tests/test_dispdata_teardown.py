"""Leaving a dispdata_text page must clear the overlay it left on the device.

Regression test for issue #9: rotating from a DispData page into a native
page left the screen polling its item list, so the panel stayed on "Loading".
"""
from __future__ import annotations

import pytest

from custom_components.divoom_times_gate.const import (
    CONF_DISPDATA_SECRET,
    CONF_SCREENS,
    SCREEN_COUNT,
)
from custom_components.divoom_times_gate.coordinator import TimesGateCoordinator

from .test_coordinator import batched_commands

DISPDATA_PAGE = {
    "page_type": "dispdata_text",
    "entity_id": "sensor.temperature",
    "duration": 60,
}
GIF_PAGE = {"page_type": "gif", "gif_id": 1, "duration": 60}


@pytest.fixture
def rotating(hass, mock_config_entry, fake_times_gate):
    """A coordinator whose screen 0 alternates dispdata_text and gif."""
    mock_config_entry.add_to_hass(hass)
    screens = [[dict(DISPDATA_PAGE), dict(GIF_PAGE)]] + [
        [{"page_type": "off"}] for _ in range(SCREEN_COUNT - 1)
    ]
    hass.config_entries.async_update_entry(
        mock_config_entry,
        data={**mock_config_entry.data, CONF_DISPDATA_SECRET: "s3cret"},
        options={**mock_config_entry.options, CONF_SCREENS: screens},
    )
    hass.states.async_set("sensor.temperature", "21.5")
    hass.config.internal_url = "http://10.0.0.2:8123"
    coord = TimesGateCoordinator(hass, mock_config_entry, fake_times_gate, 15)
    coord._first_run = False
    yield coord
    coord._debounced_refresh.async_cancel()


def clear_commands(device) -> list[dict]:
    return [
        command
        for command in batched_commands(device)
        if command.get("Command") == "Draw/ClearHttpText"
    ]


async def test_rotating_off_a_dispdata_page_clears_the_overlay(rotating) -> None:
    await rotating._async_update_data()
    assert clear_commands(rotating.device) == []

    rotating._rot_elapsed[0] = DISPDATA_PAGE["duration"]  # next tick rotates
    rotating.device.calls.clear()
    await rotating._async_update_data()

    batch = batched_commands(rotating.device)
    assert batch[0] == {"Command": "Draw/ClearHttpText", "LcdId": 0, "TextId": -1}
    assert len(batch) > 1, "the native command should ride in the same batch"


async def test_staying_on_a_dispdata_page_clears_nothing(rotating) -> None:
    await rotating._async_update_data()
    rotating.device.calls.clear()

    await rotating._async_update_data()

    assert clear_commands(rotating.device) == []


async def test_a_failed_batch_re_emits_the_teardown(rotating) -> None:
    await rotating._async_update_data()
    rotating._rot_elapsed[0] = DISPDATA_PAGE["duration"]  # next tick rotates
    rotating.device.send_command_list = _failing(rotating.device)
    await rotating._async_update_data()

    rotating.device.calls.clear()
    await rotating._async_update_data()

    assert clear_commands(rotating.device), "a rejected batch must be retried in full"


def _failing(device):
    async def send_command_list(commands):
        device.calls.append(("send_command_list", (commands,), {}))
        return {"error_code": 5}

    return send_command_list
