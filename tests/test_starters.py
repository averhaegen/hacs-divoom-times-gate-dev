"""Tests for the starter registry and the config flow's starter step.

A starter answers one question and returns whole screens. These tests pin the
two rules that keep it safe: a starter only ever writes page configuration, and
a starter that found nothing stays out of the menu instead of promising content
the system cannot produce.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.divoom_times_gate.const import (
    CONF_ACTIVE_PRESET,
    CONF_IP_ADDRESS,
    CONF_LOCAL_TOKEN,
    CONF_PRESETS,
    DEFAULT_PRESET,
    DOMAIN,
    SCREEN_COUNT,
)
from custom_components.divoom_times_gate.energy import EnergySources
from custom_components.divoom_times_gate.starters import (
    STARTERS,
    Starter,
    async_available_starters,
    get_starter,
    pad,
)

from .test_config_flow import patch_discovery, patch_ping, patch_setup


def patch_energy(found: EnergySources):
    """Patch what the energy starter discovers."""
    return patch(
        "custom_components.divoom_times_gate.energy.async_discover",
        AsyncMock(return_value=found),
    )


# --- registry --------------------------------------------------------------


def test_every_starter_has_a_key_a_name_and_a_screen_count() -> None:
    """The registry is what the menu and the tests both read."""
    keys = [starter.key for starter in STARTERS]
    assert len(keys) == len(set(keys))
    for starter in STARTERS:
        assert starter.name
        assert starter.screens in (1, SCREEN_COUNT)
        assert get_starter(starter.key) is starter


def test_get_starter_returns_none_for_an_unknown_key() -> None:
    """An unknown key means 'leave empty', not a crash."""
    assert get_starter("") is None
    assert get_starter("nope") is None


def test_pad_always_returns_five_screens() -> None:
    """Every starter's output has to cover the device, however little it found."""
    assert pad([]) == [{"page_type": "off"}] * SCREEN_COUNT
    assert len(pad([{"page_type": "clock"}] * 9)) == SCREEN_COUNT


async def test_energy_starter_is_hidden_when_nothing_is_configured(hass) -> None:
    """An empty energy dashboard means no energy option in the menu."""
    with patch_energy(EnergySources()):
        available = await async_available_starters(hass)

    assert "energy" not in [starter.key for starter, _ in available]


async def test_energy_starter_reports_what_it_found(hass) -> None:
    """The description is the availability check, so it names the sources."""
    with patch_energy(EnergySources(solar_power="sensor.pv", price_now="sensor.p")):
        available = await async_available_starters(hass)

    found = dict((starter.key, desc) for starter, desc in available)
    assert "price" in found["energy"]
    assert "solar" in found["energy"]


async def test_energy_starter_comes_first(hass) -> None:
    """Best available option first: energy leads whenever it found something."""
    with patch_energy(EnergySources(solar_power="sensor.pv")):
        available = await async_available_starters(hass)

    assert available[0][0].key == "energy"


async def test_energy_starter_fills_all_five_screens(hass) -> None:
    """Picking energy and doing nothing else has to leave no screen undefined."""
    starter = get_starter("energy")
    assert starter is not None
    with patch_energy(EnergySources(solar_power="sensor.pv", battery_soc="sensor.b")):
        screens = await starter.async_build(hass)

    assert len(screens) == SCREEN_COUNT
    assert all(isinstance(page, dict) and page.get("page_type") for page in screens)


async def test_clock_weather_starter_uses_the_first_weather_entity(hass) -> None:
    """The pick is sorted, so it does not change between runs."""
    hass.states.async_set("weather.zzz_last", "sunny", {"temperature": 20})
    hass.states.async_set("weather.aaa_first", "cloudy", {"temperature": 18})
    starter = get_starter("clock_weather")
    assert starter is not None

    assert "weather.aaa_first" in (await starter.async_available(hass) or "")
    screens = await starter.async_build(hass)

    assert screens[0]["page_type"] == "clock"
    assert screens[1]["card"] == "sensor_grid"
    assert all("weather.aaa_first" in slot["entity_id"] for slot in screens[1]["slots"])


async def test_clock_weather_starter_works_without_any_weather_entity(hass) -> None:
    """No weather entity still gives a clock rather than nothing at all."""
    starter = get_starter("clock_weather")
    assert starter is not None

    assert await starter.async_available(hass) == "clock"
    screens = await starter.async_build(hass)

    assert screens[0]["page_type"] == "clock"
    assert screens[1] == {"page_type": "off"}


@pytest.mark.parametrize("starter", STARTERS, ids=lambda s: s.key)
async def test_a_starter_never_talks_to_the_device(hass, starter: Starter) -> None:
    """Generators write configuration only, so the coordinator stays in charge."""
    hass.states.async_set("weather.home", "sunny", {"temperature": 20})
    with (
        patch_energy(EnergySources(solar_power="sensor.pv")),
        patch("custom_components.divoom_times_gate.device.TimesGate._send") as send,
    ):
        await starter.async_build(hass)

    assert send.call_count == 0


# --- config flow step ------------------------------------------------------


async def start_flow(hass):
    """Get to the starter menu with a reachable device."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_IP_ADDRESS: "192.168.1.25", CONF_LOCAL_TOKEN: 123456},
    )


async def test_user_step_ends_in_the_starter_menu(hass) -> None:
    """The entry is not created until the user says what goes on the screens."""
    with patch_discovery(), patch_ping(True), patch_energy(EnergySources()):
        result = await start_flow(hass)

    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "starter"
    assert "starter_none" in result["menu_options"]


async def test_starter_menu_hides_starters_that_found_nothing(hass) -> None:
    """No energy dashboard, no energy menu entry."""
    with patch_discovery(), patch_ping(True), patch_energy(EnergySources()):
        result = await start_flow(hass)

    assert "starter_energy" not in result["menu_options"]


async def test_starter_menu_offers_energy_when_it_found_something(hass) -> None:
    """A configured energy dashboard puts energy at the top of the menu."""
    with (
        patch_discovery(),
        patch_ping(True),
        patch_energy(EnergySources(solar_power="sensor.pv")),
    ):
        result = await start_flow(hass)

    assert result["menu_options"][0] == "starter_energy"
    assert "solar" in result["description_placeholders"]["found"]


async def test_leaving_the_screens_empty_creates_an_entry_without_options(
    hass,
) -> None:
    """Choosing nothing must not write a layout the user did not ask for."""
    with (
        patch_discovery(),
        patch_ping(True),
        patch_setup(),
        patch_energy(EnergySources()),
    ):
        result = await start_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "starter_none"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {}


async def test_picking_a_starter_writes_five_screens_into_the_default_layout(
    hass,
) -> None:
    """One click has to be enough to end up with five filled screens."""
    hass.states.async_set("weather.home", "sunny", {"temperature": 20})
    with (
        patch_discovery(),
        patch_ping(True),
        patch_setup(),
        patch_energy(EnergySources()),
    ):
        result = await start_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "starter_clock_weather"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    options = result["options"]
    assert options[CONF_ACTIVE_PRESET] == DEFAULT_PRESET
    assert len(options[CONF_PRESETS][DEFAULT_PRESET]) == SCREEN_COUNT
