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
from custom_components.divoom_times_gate.defaults import DEFAULT_CLOCK_FACE
from custom_components.divoom_times_gate.energy import EnergySources
from custom_components.divoom_times_gate.starters import (
    STARTERS,
    Starter,
    async_available_starters,
    async_clock_face,
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


# --- single-screen starters ------------------------------------------------


async def test_single_screen_starters_return_exactly_one_screen(hass) -> None:
    """A screens=1 starter fills one screen, so it can be used per screen."""
    hass.states.async_set("weather.home", "sunny", {"temperature": 4, "humidity": 80})
    hass.states.async_set("person.alex", "home")
    hass.states.async_set("calendar.work", "on", {"message": "Standup"})
    hass.states.async_set(
        "sensor.living_temp", "20", {"device_class": "temperature"}
    )

    for starter, _found in await async_available_starters(hass, screens=1):
        built = await starter.async_build(hass)
        assert len(built) == 1, starter.key


@pytest.mark.parametrize(
    ("key", "states"),
    [
        ("weather", {"weather.home": ("sunny", {})}),
        (
            "climate_air",
            {"sensor.co2": ("600", {"device_class": "carbon_dioxide"})},
        ),
        ("presence", {"person.alex": ("home", {})}),
        ("calendar_clock", {"calendar.work": ("on", {"message": "Standup"})}),
    ],
)
async def test_a_starter_is_hidden_until_it_finds_something(hass, key, states) -> None:
    starter = get_starter(key)
    assert starter is not None
    assert await starter.async_available(hass) is None

    for entity_id, (state, attributes) in states.items():
        hass.states.async_set(entity_id, state, attributes)
    assert await starter.async_available(hass) is not None


async def test_generated_slots_stay_editable_by_the_form(hass) -> None:
    """Plain entity_id slots keep the per-screen form available afterwards."""
    from custom_components.divoom_times_gate import page_forms

    hass.states.async_set("person.alex", "home")
    hass.states.async_set("binary_sensor.front", "on", {"device_class": "door"})
    starter = get_starter("presence")
    assert starter is not None

    built = await starter.async_build(hass)
    assert page_forms.unsupported_reason(built[0]) is None


async def test_the_calendar_starter_rotates_a_native_clock_and_the_agenda(
    hass,
) -> None:
    """The clock half is drawn by the device, so it costs no polling."""
    hass.states.async_set("calendar.work", "on", {"message": "Standup"})
    starter = get_starter("calendar_clock")
    assert starter is not None

    screen = (await starter.async_build(hass))[0]
    assert [page["page_type"] for page in screen] == ["dispdata_text", "card"]
    assert {item["kind"] for item in screen[0]["items"]} == {
        "time_short",
        "weekday_full",
        "month_day",
    }


async def test_climate_air_puts_indoor_entities_before_outdoor_ones(hass) -> None:
    """Room comfort is what people look at, so it goes first."""
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import entity_registry as er

    areas = ar.async_get(hass)
    garden = areas.async_create("Garden")
    registry = er.async_get(hass)
    outside = registry.async_get_or_create(
        "sensor", "demo", "outside", suggested_object_id="outside_temp"
    )
    registry.async_update_entity(outside.entity_id, area_id=garden.id)
    hass.states.async_set(outside.entity_id, "4", {"device_class": "temperature"})
    hass.states.async_set("sensor.a_living_temp", "20", {"device_class": "temperature"})

    starter = get_starter("climate_air")
    assert starter is not None
    slots = (await starter.async_build(hass))[0]["slots"]

    assert [slot["entity_id"] for slot in slots][-1] == outside.entity_id


# --- resolving the clock face ----------------------------------------------
#
# The shipped face id is checked against Divoom's live catalog before it is
# written. That proves the id still exists today. It does not prove the face
# renders well on any given hardware revision: GetDialType and GetDialList take
# no DeviceId, so every LCD device gets the same catalog.


def patch_catalog(catalog: dict[str, dict[int, str]]):
    """Patch the per-screen face catalog the resolver reads."""
    return patch(
        "custom_components.divoom_times_gate.starters."
        "async_get_per_screen_face_catalog",
        AsyncMock(return_value=catalog),
    )


async def test_the_shipped_face_wins_when_it_is_still_in_the_catalog(hass) -> None:
    """It is the one id verified on a real device, so prefer it."""
    with patch_catalog(
        {"Normal": {10: "Classic Digital Clock"}, "Nature&Weather": {152: "Big Time"}}
    ):
        assert await async_clock_face(hass) == DEFAULT_CLOCK_FACE


async def test_a_retired_face_falls_back_to_the_first_normal_clock(hass) -> None:
    """Divoom can pull a face. Pixel Art is skipped: it holds blank slots."""
    with patch_catalog(
        {
            "Pixel Art": {1114: "Custom 1 watch face"},
            "Normal": {10: "Classic Digital Clock", 122: "wrist watch"},
        }
    ):
        assert await async_clock_face(hass) == 10


async def test_an_unreachable_cloud_keeps_the_shipped_face(hass) -> None:
    """Setup must never break on this. An empty catalog means no answer."""
    with patch_catalog({}):
        assert await async_clock_face(hass) == DEFAULT_CLOCK_FACE


async def test_a_catalog_without_normal_clocks_keeps_the_shipped_face(hass) -> None:
    with patch_catalog({"Pixel Art": {1114: "Custom 1 watch face"}}):
        assert await async_clock_face(hass) == DEFAULT_CLOCK_FACE


async def test_the_face_is_resolved_once_per_home_assistant(hass) -> None:
    """Five starters in a row must not mean five round trips to the cloud."""
    catalog = AsyncMock(return_value={"Normal": {10: "Classic Digital Clock"}})
    with patch(
        "custom_components.divoom_times_gate.starters."
        "async_get_per_screen_face_catalog",
        catalog,
    ):
        first = await async_clock_face(hass)
        assert [await async_clock_face(hass) for _ in range(4)] == [first] * 4

    assert catalog.await_count == 1


async def test_the_clock_and_weather_starter_uses_the_resolved_face(hass) -> None:
    with patch_catalog({"Normal": {10: "Classic Digital Clock"}}):
        starter = get_starter("clock_weather")
        assert starter is not None
        built = await starter.async_build(hass)

    assert built[0] == {"page_type": "clock", "clock_id": 10}


async def test_the_setup_starter_writes_the_resolved_face_into_the_options(
    hass,
) -> None:
    """The choice falls once. After that it is ordinary configuration."""
    with patch_catalog({"Normal": {10: "Classic Digital Clock"}}):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}
        )
        with patch_discovery([]), patch_ping(True):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_IP_ADDRESS: "1.2.3.4", CONF_LOCAL_TOKEN: 1},
            )
        with patch_setup():
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {"next_step_id": "starter_clock_weather"}
            )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    screens = result["options"][CONF_PRESETS][DEFAULT_PRESET]
    assert screens[0] == {"page_type": "clock", "clock_id": 10}
