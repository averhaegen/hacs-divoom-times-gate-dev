"""Tests for energy discovery, the energy panels and the preset layer."""
from __future__ import annotations

from unittest.mock import patch

from homeassistant.helpers.template import Template
import pytest

from custom_components.divoom_times_gate import energy, energy_cards, graphs, presets
from custom_components.divoom_times_gate.const import (
    CONF_ACTIVE_PRESET,
    CONF_PRESETS,
    CONF_SCREENS,
    DEFAULT_PRESET,
    ENERGY_HERO_CHAR_WIDTH,
    ENERGY_HERO_FONT,
    ENERGY_PRESET,
    SCREEN_SIZE,
)
from custom_components.divoom_times_gate.units import quantize_fraction

FLAT_GRID = {
    "type": "grid",
    "stat_energy_from": "sensor.from_grid",
    "stat_energy_to": "sensor.to_grid",
    "entity_energy_price": "sensor.price",
    "power_config": {
        "stat_rate_from": "sensor.power_from_grid",
        "stat_rate_to": "sensor.power_to_grid",
    },
    "stat_rate": "sensor.net_power",
}

NESTED_GRID = {
    "type": "grid",
    "flow_from": [
        {
            "stat_energy_from": "sensor.from_grid",
            "entity_energy_price": "sensor.price",
            "power_config": {"stat_rate": "sensor.power_from_grid"},
        }
    ],
    "flow_to": [
        {
            "stat_energy_to": "sensor.to_grid",
            "power_config": {"stat_rate": "sensor.power_to_grid"},
        }
    ],
}

SOLAR = {
    "type": "solar",
    "stat_energy_from": "sensor.solar_energy",
    "power_config": {"stat_rate": "sensor.solar_power"},
}
BATTERY = {
    "type": "battery",
    "stat_energy_from": "sensor.battery_out",
    "stat_energy_to": "sensor.battery_in",
    "stat_soc": "sensor.battery_soc",
    "power_config": {"stat_rate": "sensor.battery_power"},
}


@pytest.mark.parametrize("grid", [FLAT_GRID, NESTED_GRID], ids=["flat", "nested"])
def test_parse_sources_handles_both_grid_schemas(grid) -> None:
    found = energy.parse_sources({"energy_sources": [grid, SOLAR, BATTERY]})

    assert found.grid_import_stat == "sensor.from_grid"
    assert found.grid_export_stat == "sensor.to_grid"
    assert found.grid_import_power == "sensor.power_from_grid"
    assert found.grid_export_power == "sensor.power_to_grid"
    assert found.price_now == "sensor.price"
    assert found.has_electricity
    assert found.has_solar
    assert found.has_battery
    assert found.solar_power == "sensor.solar_power"
    assert found.battery_soc == "sensor.battery_soc"


def test_parse_sources_reads_gas_and_water() -> None:
    found = energy.parse_sources(
        {
            "energy_sources": [{"type": "gas", "stat_energy_from": "nhc2:abc_gasvolume"}],
            "device_consumption_water": [{"stat_consumption": "sensor.water"}],
        }
    )

    assert found.gas_stat == "nhc2:abc_gasvolume"
    assert found.water_stats == ["sensor.water"]
    assert not found.has_electricity


def test_parse_sources_tolerates_an_empty_configuration() -> None:
    found = energy.parse_sources({})

    assert not found.has_electricity
    assert found.water_stats == []
    assert found.solar_forecast_entries == []


def test_parse_sources_reads_solar_forecast_entries() -> None:
    solar = {**SOLAR, "config_entry_solar_forecast": ["abc123", "def456"]}
    found = energy.parse_sources({"energy_sources": [solar]})

    assert found.solar_forecast_entries == ["abc123", "def456"]


def test_parse_sources_without_forecast_entries_still_discovers_solar() -> None:
    # The key is absent here, and the older config also stores it as None, so a
    # solar source must still discover normally without a forecast.
    for solar in (SOLAR, {**SOLAR, "config_entry_solar_forecast": None}):
        found = energy.parse_sources({"energy_sources": [solar]})

        assert found.has_solar
        assert found.solar_forecast_entries == []


def test_house_power_template_combines_every_source() -> None:
    found = energy.parse_sources({"energy_sources": [FLAT_GRID, SOLAR, BATTERY]})

    template = energy.house_power_template(found)

    assert "sensor.power_from_grid" in template
    assert "- states('sensor.power_to_grid')" in template
    assert "sensor.solar_power" in template
    assert template.startswith("{{") and template.endswith("}}")


def test_house_power_template_inverts_the_battery_on_request() -> None:
    found = energy.parse_sources({"energy_sources": [BATTERY]})

    normal = energy.house_power_template(found)
    inverted = energy.house_power_template(found, battery_discharge_positive=False)

    assert normal != inverted


def test_house_power_template_without_sources_is_zero() -> None:
    assert energy.house_power_template(energy.parse_sources({})) == "{{ 0 }}"


async def test_find_price_forecast_prefers_the_closest_name(hass) -> None:
    hass.states.async_set(
        "sensor.engie_average_price",
        "0.1",
        {"prices": [{"time": "t", "price": 0.1}] * 48},
    )
    hass.states.async_set(
        "sensor.other_average_price",
        "0.1",
        {"prices": [{"time": "t", "price": 0.1}] * 48},
    )

    found = energy.find_price_forecast(hass, "sensor.engie_current_price")

    assert found == "sensor.engie_average_price"


async def test_find_price_forecast_ignores_short_lists(hass) -> None:
    hass.states.async_set("sensor.a_price", "0.1", {"prices": [1, 2]})

    assert energy.find_price_forecast(hass, "sensor.a_current") is None


async def test_find_price_forecast_without_a_price_entity(hass) -> None:
    assert energy.find_price_forecast(hass, None) is None


async def test_async_discover_survives_a_missing_energy_component(hass) -> None:
    found = await energy.async_discover(hass)

    assert isinstance(found, energy.EnergySources)


async def test_goal_template_resolves_forecast_entry_to_production_today(hass) -> None:
    from homeassistant.helpers import entity_registry as er
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain="forecast_solar")
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    # A same-entry sensor with another suffix must not stand in for the goal.
    registry.async_get_or_create(
        "sensor", "forecast_solar", "uid_now", config_entry=entry
    )
    registry.async_get_or_create(
        "sensor",
        "forecast_solar",
        "uid_energy_production_today",
        config_entry=entry,
        suggested_object_id="solar_energy_production_today",
    )

    found = energy.EnergySources(
        solar_power="sensor.solar_power", solar_forecast_entries=[entry.entry_id]
    )
    template = presets._forecast_solar_goal_template(hass, found)

    assert template == (
        "{{ states('sensor.solar_energy_production_today') | float(0) }}"
    )


async def test_goal_template_is_none_without_forecast_entries(hass) -> None:
    found = energy.EnergySources(solar_power="sensor.solar_power")

    assert presets._forecast_solar_goal_template(hass, found) is None


def test_read_presets_migrates_a_plain_screen_list() -> None:
    found = presets.read_presets({CONF_SCREENS: [{"page_type": "off"}]})

    assert list(found) == [DEFAULT_PRESET]


def test_read_presets_keeps_an_explicit_default() -> None:
    options = {
        CONF_SCREENS: [{"page_type": "off"}],
        CONF_PRESETS: {DEFAULT_PRESET: [{"page_type": "clock"}]},
    }

    found = presets.read_presets(options)

    assert found[DEFAULT_PRESET] == [{"page_type": "clock"}]


def test_active_screens_follows_the_active_preset() -> None:
    options = {
        CONF_PRESETS: {"a": [{"page_type": "clock"}], "b": [{"page_type": "off"}]},
        CONF_ACTIVE_PRESET: "b",
    }

    assert presets.active_screens(options) == [{"page_type": "off"}]


def test_active_screens_falls_back_when_the_preset_is_gone() -> None:
    options = {
        CONF_PRESETS: {DEFAULT_PRESET: [{"page_type": "clock"}]},
        CONF_ACTIVE_PRESET: "vanished",
    }

    assert presets.active_screens(options) == [{"page_type": "clock"}]


def test_active_screens_without_presets_reads_the_screen_list() -> None:
    assert presets.active_screens({CONF_SCREENS: [1]}) == [1]


def test_build_energy_preset_produces_five_screens() -> None:
    found = energy.parse_sources(
        {
            "energy_sources": [
                FLAT_GRID,
                SOLAR,
                BATTERY,
                {"type": "gas", "stat_energy_from": "sensor.gas"},
            ],
            "device_consumption_water": [{"stat_consumption": "sensor.water"}],
        }
    )

    screens = presets.build_energy_preset(found)

    assert len(screens) == 5
    # Solar and battery merge onto one screen, and the fifth carries the history.
    assert [s.get("mode") for s in screens[:3]] == ["price", "power", "solar_battery"]
    assert screens[3]["card"] == "graph"
    # The day-ahead graph no longer carries the footer, so it stays full height.
    assert "footer_slots" not in screens[3]
    assert "footer_height" not in screens[3]
    # Gas and water moved onto the house screen.
    assert screens[1]["footer_height"] == 32
    assert [slot["name"] for slot in screens[1]["footer_slots"]] == ["Gas", "Water"]
    assert screens[4]["card"] == "energy_history"


def test_build_energy_preset_blanks_missing_sources() -> None:
    screens = presets.build_energy_preset(energy.parse_sources({"energy_sources": [FLAT_GRID]}))

    # No solar and no battery, so the merged screen blanks. The grid statistics
    # still drive a consumption history, so screen five is a graph, not off.
    assert screens[2] == {"page_type": "off"}
    assert screens[3]["card"] == "graph"
    assert "footer_height" not in screens[3]
    assert screens[4]["card"] == "energy_history"


def test_build_energy_preset_reads_a_statistic_only_gas_from_the_recorder() -> None:
    found = energy.parse_sources(
        {"energy_sources": [{"type": "gas", "stat_energy_from": "nhc2:abc_gasvolume"}]}
    )

    slot = presets.build_energy_preset(found)[1]["footer_slots"][0]

    assert slot["stat"] == "nhc2:abc_gasvolume"
    assert "entity_id" not in slot
    assert slot["unit"] == "m\u00b3"


def test_build_energy_preset_reads_a_meter_backed_water_as_a_daily_total() -> None:
    found = energy.parse_sources(
        {"energy_sources": [{"type": "water", "stat_energy_from": "sensor.energyhome_water"}]}
    )

    slot = presets.build_energy_preset(found)[1]["footer_slots"][0]

    # A water meter counts up forever, so its state is the meter reading rather
    # than today's usage. Read the statistic and keep the entity as a fallback.
    assert slot["stat"] == "sensor.energyhome_water"
    assert slot["entity_id"] == "sensor.energyhome_water"
    assert slot["unit"] == "L"


async def test_graph_footer_prefers_the_daily_total_over_the_meter_reading(hass) -> None:
    page = {
        "card": "graph",
        "data_template": "[1, 2, 3]",
        "footer_height": 32,
        "footer_slots": [
            {"stat": "nhc2:abc_gasvolume", "name": "Gas", "unit": "m\u00b3"},
            {"stat": "sensor.water", "entity_id": "sensor.water", "name": "Water", "unit": "L"},
        ],
    }

    with patch(
        "custom_components.divoom_times_gate.energy.async_daily_totals",
        return_value={"nhc2:abc_gasvolume": 3.25, "sensor.water": 10.0},
    ) as totals:
        prepared = await graphs.async_prepare_graph(hass, page)

    assert totals.call_args[0][1] == ["nhc2:abc_gasvolume", "sensor.water"]
    assert prepared["_footer_totals"] == {"nhc2:abc_gasvolume": 3.25, "sensor.water": 10.0}

    gif, items = graphs.render_graph(hass, prepared, "http://h/dispdata/secret")

    assert gif.startswith(b"GIF")
    # Both totals are drawn into the artwork, so neither is polled live.
    assert [item["TextId"] for item in items if item["TextId"] >= 10] == []


async def test_graph_footer_polls_a_slot_the_recorder_has_no_statistic_for(hass) -> None:
    page = {
        "card": "graph",
        "data_template": "[1, 2, 3]",
        "footer_height": 32,
        "footer_slots": [
            {"stat": "sensor.water", "entity_id": "sensor.water", "name": "Water", "unit": "L"},
        ],
    }

    with patch(
        "custom_components.divoom_times_gate.energy.async_daily_totals", return_value={}
    ):
        prepared = await graphs.async_prepare_graph(hass, page)

    _, items = graphs.render_graph(hass, prepared, "http://h/dispdata/secret")

    assert [item["TextId"] for item in items if item["TextId"] >= 10] == [10]


async def test_graph_footer_totals_survive_a_recorder_failure(hass) -> None:
    page = {
        "card": "graph",
        "data_template": "[1, 2]",
        "footer_height": 32,
        "footer_slots": [{"stat": "nhc2:abc", "name": "Gas"}],
    }

    with patch(
        "custom_components.divoom_times_gate.energy.async_daily_totals",
        side_effect=RuntimeError("recorder is busy"),
    ):
        prepared = await graphs.async_prepare_graph(hass, page)

    assert prepared["_footer_totals"] == {}
    assert graphs.render_graph(hass, prepared, "http://h/dispdata/s")[0].startswith(b"GIF")


def test_with_energy_preset_keeps_the_previous_screens() -> None:
    options = {CONF_SCREENS: [{"page_type": "clock"}]}

    updated = presets.with_energy_preset(options, [{"page_type": "off"}])

    assert updated[CONF_ACTIVE_PRESET] == ENERGY_PRESET
    assert updated[CONF_PRESETS][DEFAULT_PRESET] == [{"page_type": "clock"}]
    assert updated[CONF_PRESETS][ENERGY_PRESET] == [{"page_type": "off"}]


@pytest.mark.parametrize("mode", ["price", "power", "battery", "solar"])
async def test_energy_panels_render_and_emit_overlays(hass, mode) -> None:
    page = {
        "mode": mode,
        "entity_id": "sensor.value",
        "_current": 0.184,
        "_battery_power": -400.0,
        "_totals": {"sensor.stat": 4.2},
        "price_min": 0.1,
        "price_max": 0.3,
        "import_entity": "sensor.power_from_grid",
        "export_entity": "sensor.power_to_grid",
        "import_stat": "sensor.stat",
        "power_entity": "sensor.battery_power",
        "solar_stat": "sensor.stat",
        "_curve": [0, 10, 40, 20],
    }

    gif, items = energy_cards.render_energy_panel(hass, page, "http://h/dispdata/secret")

    assert gif.startswith(b"GIF")
    assert items and all(item["type"] == 23 for item in items)
    assert all(item["update_time"] == 10 for item in items)


async def test_energy_panel_rejects_an_unknown_mode(hass) -> None:
    with pytest.raises(ValueError, match="unknown mode"):
        energy_cards.render_energy_panel(hass, {"mode": "weather"}, "http://h/dispdata/s")

    with pytest.raises(ValueError, match="unknown mode"):
        await energy_cards.async_prepare_energy_panel(hass, {"mode": "weather"})


async def test_energy_panel_prepare_reads_states_and_totals(hass) -> None:
    hass.states.async_set("sensor.value", "0.2")
    hass.states.async_set("sensor.battery_power", "-350")

    with patch(
        "custom_components.divoom_times_gate.energy.async_daily_totals",
        return_value={"sensor.stat": 1.5},
    ):
        prepared = await energy_cards.async_prepare_energy_panel(
            hass,
            {
                "mode": "battery",
                "entity_id": "sensor.value",
                "battery_power_entity": "sensor.battery_power",
                "import_stat": "sensor.stat",
            },
        )

    assert prepared["_current"] == 0.2
    assert prepared["_battery_power"] == -350.0
    assert prepared["_totals"] == {"sensor.stat": 1.5}


async def test_energy_panel_prepare_renders_price_bounds(hass) -> None:
    prepared = await energy_cards.async_prepare_energy_panel(
        hass, {"mode": "price", "price_min_template": "{{ 0.05 }}"}
    )

    assert prepared["price_min"] == 0.05


@pytest.mark.parametrize(
    ("unit", "state", "expected"),
    [
        ("W", "1500", "1.50"),
        ("kW", "2.5", "2.50"),
        ("MW", "0.004", "4.00"),
        ("mW", "1500000", "1.50"),
        ("", "40", "0.04"),
    ],
)
async def test_energy_panel_renders_every_power_unit_as_kilowatts(
    hass, unit, state, expected
) -> None:
    hass.states.async_set("sensor.value", state, {"unit_of_measurement": unit})

    prepared = await energy_cards.async_prepare_energy_panel(
        hass, {"mode": "solar", "entity_id": "sensor.value"}
    )

    assert prepared["_hero_unit"] == "kW"
    rendered = Template(prepared["_hero_template"], hass).async_render(parse_result=False)
    assert rendered == expected


async def test_energy_panel_drops_the_sign_from_a_battery_rate(hass) -> None:
    hass.states.async_set(
        "sensor.rate", "-1234", {"unit_of_measurement": "W"}
    )

    prepared = await energy_cards.async_prepare_energy_panel(
        hass, {"mode": "battery", "power_entity": "sensor.rate"}
    )

    rendered = Template(
        prepared["_row_templates"]["power"], hass
    ).async_render(parse_result=False)
    assert rendered == "1.23"


async def test_energy_panel_centres_a_value_against_its_unit(hass) -> None:
    hass.states.async_set("sensor.value", "0.184")

    page = await energy_cards.async_prepare_energy_panel(
        hass, {"mode": "price", "entity_id": "sensor.value"}
    )
    _, items = energy_cards.render_energy_panel(hass, page, "http://h/dispdata/s")

    # The firmware places text inside the item box itself, so the box is cut to
    # the number and centred as a whole. See docs/API.md §4.10.
    hero = items[0]
    assert hero["font"] == ENERGY_HERO_FONT
    assert hero["TextWidth"] == 5 * ENERGY_HERO_CHAR_WIDTH
    assert hero["x"] == SCREEN_SIZE - (hero["x"] + hero["TextWidth"])


async def test_daily_totals_ask_the_recorder_for_kilowatt_hours(hass) -> None:
    """A watt hour meter must not read a thousand times too high.

    The recorder converts to the sensor's own unit unless it is told
    otherwise, so the request pins energy to kWh.
    """
    captured: dict[str, object] = {}

    def fake_statistics(hass, start, end, statistic_ids, period, units, types):
        captured["units"] = units
        captured["types"] = types
        return {"sensor.solar": [{"change": 12.0}, {"change": 18.618}]}

    class _Recorder:
        async def async_add_executor_job(self, func, *args):
            return func(*args)

    hass.data.pop("divoom_times_gate_energy_totals", None)
    with (
        patch(
            "homeassistant.components.recorder.statistics.statistics_during_period",
            fake_statistics,
        ),
        patch("homeassistant.components.recorder.get_instance", return_value=_Recorder()),
    ):
        totals = await energy.async_daily_totals(hass, ["sensor.solar"])

    assert captured["units"] == {"energy": "kWh"}
    assert captured["types"] == {"change"}
    assert totals["sensor.solar"] == pytest.approx(30.618)


@pytest.mark.parametrize(
    ("value", "lo", "hi", "step", "expected"),
    [
        (0.0, 0.0, 100.0, 0.1, 0.0),  # bottom clamps to zero
        (100.0, 0.0, 100.0, 0.1, 1.0),  # top clamps to one
        (-5.0, 0.0, 100.0, 0.1, 0.0),  # below range clamps
        (250.0, 0.0, 100.0, 0.1, 1.0),  # above range clamps
        (55.0, 0.0, 100.0, 0.1, 0.5),  # snaps down, not to nearest
        (5.0, 0.0, 100.0, 0.1, 0.0),  # a value below one band reads as empty
        (0.5, 0.0, 1.0, 1.0, 0.0),  # a coarse step floors the middle
        (5.0, 5.0, 5.0, 0.1, 0.0),  # a zero-width range is safe
        (5.0, 10.0, 5.0, 0.1, 0.0),  # an inverted range is safe
    ],
)
def test_quantize_fraction_edges(value, lo, hi, step, expected) -> None:
    assert quantize_fraction(value, lo, hi, step) == pytest.approx(expected)


def test_quantize_fraction_places_a_bipolar_zero() -> None:
    # abs(power_min) / (power_max - power_min) is where 0 W sits on the bar.
    assert quantize_fraction(0.0, -2500.0, 800.0, 0.1) == pytest.approx(0.7)


PRICES_TODAY = [
    {"time": "2026-08-24T07:00:00+02:00", "price": 0.206},
    {"time": "2026-08-24T13:00:00+02:00", "price": 0.030},
    {"time": "2026-08-24T18:00:00+02:00", "price": 0.120},
]


async def test_price_page_extracts_cheapest_and_priciest_time(hass) -> None:
    await hass.config.async_set_time_zone("Europe/Brussels")
    hass.states.async_set(
        "sensor.engie_average_price", "0.1", {"prices_today": PRICES_TODAY}
    )
    found = energy.EnergySources(
        price_now="sensor.engie_current", price_forecast="sensor.engie_average_price"
    )

    panel, _ = presets._price_pages(found)
    prepared = await energy_cards.async_prepare_energy_panel(hass, panel)

    assert prepared["cheapest_time"] == "13:00"
    assert prepared["priciest_time"] == "07:00"


async def test_price_page_draws_nothing_for_a_malformed_price_list(hass) -> None:
    hass.states.async_set("sensor.engie_average_price", "0.1", {"prices_today": "oops"})
    found = energy.EnergySources(
        price_now="sensor.engie_current", price_forecast="sensor.engie_average_price"
    )

    panel, _ = presets._price_pages(found)
    prepared = await energy_cards.async_prepare_energy_panel(hass, panel)

    assert prepared.get("cheapest_time", "") == ""
    assert prepared.get("priciest_time", "") == ""


def test_goal_bar_fraction_caps_at_one() -> None:
    from PIL import Image, ImageDraw

    draw = ImageDraw.Draw(Image.new("RGB", (128, 128)))

    # Over the goal: the fraction caps at 1.0, so the bar draws and returns True.
    assert energy_cards._draw_goal_bar(
        draw, {"goal": 24}, "#000000", "#ff9800", 30.0, x=12, y=34, w=104, h=6
    )
    # No goal set: keep the plain caption, so the helper returns False.
    assert not energy_cards._draw_goal_bar(
        draw, {"goal": 0}, "#000000", "#ff9800", 18.3, x=12, y=34, w=104, h=6
    )


@pytest.mark.parametrize(
    ("soc", "charging", "expected"),
    [
        (100.0, False, "mdi:battery"),
        (0.0, False, "mdi:battery-outline"),
        (46.0, False, "mdi:battery-50"),
        (44.0, False, "mdi:battery-40"),
        (100.0, True, "mdi:battery-charging-100"),
        (55.0, True, "mdi:battery-charging-60"),
        (0.0, True, "mdi:battery-charging-outline"),
        (-5.0, False, "mdi:battery-outline"),
        (250.0, False, "mdi:battery"),
    ],
)
def test_battery_band_icon_selection(soc, charging, expected) -> None:
    assert energy_cards._battery_band_icon(soc, charging) == expected


def test_battery_band_icons_exist_in_the_font() -> None:
    from custom_components.divoom_times_gate.mdi import icon_char

    for soc in range(0, 101, 10):
        for charging in (False, True):
            assert icon_char(energy_cards._battery_band_icon(float(soc), charging))


def test_round_power_range_rounds_outward() -> None:
    assert energy.round_power_range(-2430.0, 780.0) == (-2500.0, 800.0)
    assert energy.round_power_range(-455.0, 118.0) == (-460.0, 120.0)


async def test_async_power_range_reads_seven_day_min_max(hass) -> None:
    captured: dict[str, object] = {}

    def fake_statistics(hass, start, end, statistic_ids, period, units, types):
        captured["period"] = period
        captured["types"] = types
        return {"sensor.battery_power": [{"min": -2430.0, "max": 780.0}]}

    class _Recorder:
        async def async_add_executor_job(self, func, *args):
            return func(*args)

    hass.data.pop("divoom_times_gate_energy_power_range", None)
    with (
        patch(
            "homeassistant.components.recorder.statistics.statistics_during_period",
            fake_statistics,
        ),
        patch("homeassistant.components.recorder.get_instance", return_value=_Recorder()),
    ):
        low, high = await energy.async_power_range(hass, "sensor.battery_power", -400.0)

    assert captured["period"] == "day"
    assert captured["types"] == {"min", "max"}
    assert (low, high) == (-2500.0, 800.0)


async def test_async_power_range_falls_back_without_data(hass) -> None:
    class _Recorder:
        async def async_add_executor_job(self, func, *args):
            return {}

    hass.data.pop("divoom_times_gate_energy_power_range", None)
    with (
        patch("homeassistant.components.recorder.statistics.statistics_during_period"),
        patch("homeassistant.components.recorder.get_instance", return_value=_Recorder()),
    ):
        low, high = await energy.async_power_range(hass, "sensor.battery_power", -400.0)

    # Symmetric around the current value, and never zero-width.
    assert low == -400.0 and high == 400.0
    assert high > low


async def test_async_power_range_default_span_without_a_statistic(hass) -> None:
    # An empty statistic id short-circuits to the default symmetric span.
    low, high = await energy.async_power_range(hass, "", None)

    assert low < 0 < high


def test_merged_preset_produces_four_panels_and_a_history_slot() -> None:
    found = energy.parse_sources({"energy_sources": [FLAT_GRID, SOLAR, BATTERY]})

    screens = presets.build_energy_preset(found)

    assert len(screens) == 5
    merged = screens[2]
    assert merged["mode"] == "solar_battery"
    assert merged["solar_stat"] == "sensor.solar_energy"
    assert merged["battery_soc"] == "sensor.battery_soc"
    assert merged["goal"] == 0
    assert screens[4]["card"] == "energy_history"


def test_merged_preset_falls_back_to_solar_only() -> None:
    found = energy.parse_sources({"energy_sources": [FLAT_GRID, SOLAR]})

    merged = presets.build_energy_preset(found)[2]

    assert merged["mode"] == "solar_battery"
    assert merged["solar_stat"] == "sensor.solar_energy"
    assert "battery_soc" not in merged
    # Solar is the hero when there is no battery.
    assert merged["entity_id"] == "sensor.solar_power"


def test_merged_preset_falls_back_to_battery_only() -> None:
    found = energy.parse_sources({"energy_sources": [FLAT_GRID, BATTERY]})

    merged = presets.build_energy_preset(found)[2]

    assert merged["mode"] == "solar_battery"
    assert "solar_stat" not in merged
    # The state of charge is the hero when there is no solar.
    assert merged["entity_id"] == "sensor.battery_soc"


def test_merged_preset_blanks_without_solar_or_battery() -> None:
    found = energy.parse_sources({"energy_sources": [FLAT_GRID]})

    assert presets.build_energy_preset(found)[2] == {"page_type": "off"}


@pytest.mark.parametrize(
    "sources",
    [
        [FLAT_GRID, SOLAR, BATTERY],
        [FLAT_GRID, SOLAR],
        [FLAT_GRID, BATTERY],
    ],
    ids=["both", "solar_only", "battery_only"],
)
async def test_merged_panel_renders(hass, sources) -> None:
    hass.states.async_set("sensor.solar_power", "1200", {"unit_of_measurement": "W"})
    hass.states.async_set("sensor.battery_soc", "55", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.battery_power", "-400", {"unit_of_measurement": "W"})
    page = presets.build_energy_preset(energy.parse_sources({"energy_sources": sources}))[2]

    with patch(
        "custom_components.divoom_times_gate.energy.async_daily_totals",
        return_value={"sensor.solar_energy": 18.3},
    ):
        prepared = await energy_cards.async_prepare_energy_panel(hass, page)

    gif, items = energy_cards.render_energy_panel(hass, prepared, "http://h/dispdata/secret")

    assert gif.startswith(b"GIF")
    assert all(item["type"] == 23 for item in items)


def _hourly_rows(hour_to_change: dict[int, float]) -> list[dict[str, float]]:
    """Build recorder-shaped hourly change rows for a UTC day at 2026-08-24."""
    from datetime import UTC, datetime

    midnight = datetime(2026, 8, 24, tzinfo=UTC).timestamp()
    return [
        {"start": midnight + hour * 3600, "change": change}
        for hour, change in sorted(hour_to_change.items())
    ]


async def test_hourly_changes_bucket_by_hour_and_ask_for_kilowatt_hours(hass) -> None:
    """The history graph needs per-hour change, in kWh, one slot per hour.

    A watt hour meter must not read a thousand times too high, so the request
    pins energy to kWh just like the daily total does. Hours that have not
    happened yet stay empty.
    """
    from freezegun import freeze_time

    await hass.config.async_set_time_zone("UTC")
    captured: dict[str, object] = {}

    def fake_statistics(hass, start, end, statistic_ids, period, units, types):
        captured["units"] = units
        captured["period"] = period
        return {"sensor.solar": _hourly_rows({1: 1.0, 2: 2.0, 3: 1.5})}

    class _Recorder:
        async def async_add_executor_job(self, func, *args):
            return func(*args)

    hass.data.pop("divoom_times_gate_energy_totals", None)
    with (
        freeze_time("2026-08-24 05:30:00"),
        patch(
            "homeassistant.components.recorder.statistics.statistics_during_period",
            fake_statistics,
        ),
        patch("homeassistant.components.recorder.get_instance", return_value=_Recorder()),
    ):
        series = await energy.async_hourly_changes(hass, ["sensor.solar"])

    assert captured["units"] == {"energy": "kWh"}
    assert captured["period"] == "hour"
    slots = series["sensor.solar"]
    assert len(slots) == 24
    # Elapsed hours read their change, zero where nothing moved.
    assert slots[:6] == [0.0, 1.0, 2.0, 1.5, 0.0, 0.0]
    # Hours after the current one stay empty.
    assert slots[6:] == [None] * 18


async def test_daily_total_still_sums_the_hourly_change(hass) -> None:
    """The daily total shares the hourly read and sums it, kWh unchanged."""
    from freezegun import freeze_time

    await hass.config.async_set_time_zone("UTC")

    def fake_statistics(hass, start, end, statistic_ids, period, units, types):
        return {"sensor.solar": _hourly_rows({1: 1.0, 2: 2.0, 3: 1.5})}

    class _Recorder:
        async def async_add_executor_job(self, func, *args):
            return func(*args)

    hass.data.pop("divoom_times_gate_energy_totals", None)
    with (
        freeze_time("2026-08-24 05:30:00"),
        patch(
            "homeassistant.components.recorder.statistics.statistics_during_period",
            fake_statistics,
        ),
        patch("homeassistant.components.recorder.get_instance", return_value=_Recorder()),
    ):
        totals = await energy.async_daily_totals(hass, ["sensor.solar"])

    assert totals == {"sensor.solar": pytest.approx(4.5)}


def test_consumption_series_sums_grid_and_battery() -> None:
    """Consumption is import minus export plus solar plus discharge minus charge."""
    empty = [None] * 22
    series = {
        "imp": [4.0, 3.0, *empty],
        "exp": [1.0, 0.5, *empty],
        "sol": [0.0, 2.0, *empty],
        "bout": [0.5, 0.0, *empty],
        "bin": [0.0, 1.0, *empty],
    }
    page = {
        "import_stat": "imp",
        "export_stat": "exp",
        "solar_stat": "sol",
        "battery_out_stat": "bout",
        "battery_in_stat": "bin",
    }

    consumption = graphs._consumption_series(page, series)

    assert consumption is not None
    assert consumption[0] == pytest.approx(3.5)  # 4 - 1 + 0 + 0.5 - 0
    assert consumption[1] == pytest.approx(3.5)  # 3 - 0.5 + 2 + 0 - 1
    # A future hour with no contributing stat stays empty.
    assert consumption[2:] == [None] * 22


def test_consumption_series_is_none_without_a_grid_or_battery_stat() -> None:
    # Solar alone is not a consumption source, so there is no line to draw.
    assert graphs._consumption_series({"solar_stat": "sol"}, {"sol": [1.0] * 24}) is None


async def test_prepare_energy_history_splits_solar_from_consumption(hass) -> None:
    page = {
        "card": "energy_history",
        "solar_stat": "sensor.solar",
        "import_stat": "sensor.imp",
        "export_stat": "sensor.exp",
    }
    hourly = {
        "sensor.solar": [0.0, 3.0, *[None] * 22],
        "sensor.imp": [2.0, 1.0, *[None] * 22],
        "sensor.exp": [0.0, 0.5, *[None] * 22],
    }

    with patch(
        "custom_components.divoom_times_gate.energy.async_hourly_changes",
        return_value=hourly,
    ) as changes:
        prepared = await graphs.async_prepare_energy_history(hass, page)

    # Only the configured stats are read.
    assert sorted(changes.call_args[0][1]) == ["sensor.exp", "sensor.imp", "sensor.solar"]
    assert prepared["_solar_series"] == [0.0, 3.0, *[None] * 22]
    # Consumption folds import, export and solar together per hour.
    assert prepared["_consumption_series"][0] == pytest.approx(2.0)  # 2 - 0 + 0
    assert prepared["_consumption_series"][1] == pytest.approx(3.5)  # 1 - 0.5 + 3


async def test_energy_history_renders_without_overlays(hass) -> None:
    page = {
        "card": "energy_history",
        "title": "Today",
        "unit": "kWh",
        "_solar_series": [0.0, 1.0, 2.0, *[None] * 21],
        "_consumption_series": [1.0, 1.5, 2.5, *[None] * 21],
    }

    gif, items = graphs.render_energy_history(hass, page, "http://h/dispdata/s")

    assert gif.startswith(b"GIF")
    # Both series are baked artwork, so nothing is polled live.
    assert items == []


async def test_energy_history_draws_consumption_alone(hass) -> None:
    # No solar statistic, so the graph degrades to the consumption line only.
    page = {
        "card": "energy_history",
        "_solar_series": None,
        "_consumption_series": [1.0, 1.5, *[None] * 22],
    }

    gif, _ = graphs.render_energy_history(hass, page, "http://h/dispdata/s")

    assert gif.startswith(b"GIF")


async def test_energy_history_falls_back_to_no_data(hass) -> None:
    # Neither series has a value, so the graph draws the no-data treatment.
    page = {"card": "energy_history", "_solar_series": None, "_consumption_series": None}

    gif, items = graphs.render_energy_history(hass, page, "http://h/dispdata/s")

    assert gif.startswith(b"GIF")
    assert items == []


def test_history_page_carries_grid_and_solar_statistics() -> None:
    found = energy.parse_sources({"energy_sources": [FLAT_GRID, SOLAR, BATTERY]})

    history = presets.build_energy_preset(found)[4]

    assert history["card"] == "energy_history"
    assert history["solar_stat"] == "sensor.solar_energy"
    assert history["import_stat"] == "sensor.from_grid"
    assert history["export_stat"] == "sensor.to_grid"
    assert history["battery_in_stat"] == "sensor.battery_in"
    assert history["battery_out_stat"] == "sensor.battery_out"


def test_history_page_present_with_only_solar() -> None:
    # Solar but no grid: the history still draws, consumption just stays absent.
    history = presets.build_energy_preset(energy.parse_sources({"energy_sources": [SOLAR]}))[4]

    assert history["card"] == "energy_history"
    assert history["solar_stat"] == "sensor.solar_energy"
    assert history["import_stat"] is None


def test_history_page_off_without_any_source() -> None:
    # No solar and no grid statistic, so there is nothing to draw.
    screens = presets.build_energy_preset(energy.parse_sources({}))

    assert screens[4] == {"page_type": "off"}


async def test_power_panel_bakes_grid_totals_and_the_footer(hass) -> None:
    """The house screen carries baked import/export totals and the gas/water band."""
    page = presets.build_energy_preset(
        energy.parse_sources(
            {
                "energy_sources": [
                    FLAT_GRID,
                    {"type": "gas", "stat_energy_from": "sensor.gas"},
                ],
                "device_consumption_water": [{"stat_consumption": "sensor.water"}],
            }
        )
    )[1]

    assert page["footer_height"] == 32
    with patch(
        "custom_components.divoom_times_gate.energy.async_daily_totals",
        return_value={
            "sensor.from_grid": 6.4,
            "sensor.to_grid": 2.1,
            "sensor.gas": 1.2,
            "sensor.water": 30.0,
        },
    ):
        prepared = await energy_cards.async_prepare_energy_panel(hass, page)

    # The footer totals resolve the same way the price graph used to.
    assert prepared["_footer_totals"]["sensor.gas"] == 1.2
    gif, items = energy_cards.render_energy_panel(hass, prepared, "http://h/dispdata/s")

    assert gif.startswith(b"GIF")
    # Only the live house-power hero polls; the grid totals and footer are baked.
    assert [item["TextId"] for item in items] == [1]


def test_grid_totals_lead_each_figure_with_an_mdi_arrow() -> None:
    """Import and export read behind bundled MDI arrows in their own colours."""
    from PIL import Image, ImageDraw

    draw = ImageDraw.Draw(Image.new("RGB", (SCREEN_SIZE, SCREEN_SIZE)))
    calls: list[tuple[str, tuple[int, int, int]]] = []

    def _spy(_draw, icon, _xy, _size, color):
        calls.append((icon, color))
        return True

    with patch.object(energy_cards, "draw_icon", _spy):
        energy_cards._draw_grid_totals(
            draw,
            "#000000",
            y=68,
            import_total=6.4,
            export_total=2.1,
            import_color=energy_cards.ENERGY_COLORS["grid_import"],
            export_color=energy_cards.ENERGY_COLORS["grid_export"],
        )

    grid_import = tuple(
        int(energy_cards.ENERGY_COLORS["grid_import"][i : i + 2], 16) for i in (1, 3, 5)
    )
    grid_export = tuple(
        int(energy_cards.ENERGY_COLORS["grid_export"][i : i + 2], 16) for i in (1, 3, 5)
    )
    assert calls == [
        ("arrow-down-bold", grid_import),
        ("arrow-up-bold", grid_export),
    ]


def test_grid_totals_omit_the_missing_side() -> None:
    """A grid-in-only home draws just the import arrow, no export."""
    from PIL import Image, ImageDraw

    draw = ImageDraw.Draw(Image.new("RGB", (SCREEN_SIZE, SCREEN_SIZE)))
    icons: list[str] = []

    with patch.object(
        energy_cards, "draw_icon", lambda *a, **k: icons.append(a[1]) or True
    ):
        energy_cards._draw_grid_totals(
            draw,
            "#000000",
            y=68,
            import_total=6.4,
            export_total=None,
            import_color=energy_cards.ENERGY_COLORS["grid_import"],
            export_color=energy_cards.ENERGY_COLORS["grid_export"],
        )

    assert icons == ["arrow-down-bold"]


async def test_merged_battery_only_draws_a_percentage_hero_and_a_filled_bar(hass) -> None:
    """A home with a battery and no solar reads its state of charge, not 0 kW."""
    from io import BytesIO

    from PIL import Image

    hass.states.async_set("sensor.battery_soc", "73", {"unit_of_measurement": "%"})
    hass.states.async_set("sensor.battery_power", "-350", {"unit_of_measurement": "W"})
    page = presets.build_energy_preset(
        energy.parse_sources({"energy_sources": [FLAT_GRID, BATTERY]})
    )[2]

    assert page["name"] == "Battery"
    prepared = await energy_cards.async_prepare_energy_panel(hass, page)

    # The hero is the rounded state of charge with a baked percent, and the bar
    # reads the same value so it fills instead of sitting at zero.
    assert prepared["_hero_unit"] == "%"
    assert prepared["_current"] == 73.0
    rendered = Template(prepared["_hero_template"], hass).async_render(parse_result=False)
    assert rendered == "73"

    gif, items = energy_cards.render_energy_panel(hass, prepared, "http://h/dispdata/s")
    # A negative rate is charging, so the bar draws in the charge colour.
    charge = tuple(
        int(energy_cards.ENERGY_COLORS["battery_in"][i : i + 2], 16) for i in (1, 3, 5)
    )
    image = Image.open(BytesIO(gif)).convert("RGB")
    colours = {colour for _, colour in image.getcolors(maxcolors=100000)}
    assert charge in colours


async def test_merged_solar_only_keeps_the_kilowatt_hero(hass) -> None:
    """A home with solar and no battery still reads current production in kW."""
    hass.states.async_set("sensor.solar_power", "2500", {"unit_of_measurement": "W"})
    page = presets.build_energy_preset(
        energy.parse_sources({"energy_sources": [FLAT_GRID, SOLAR]})
    )[2]

    assert page["name"] == "Solar"
    prepared = await energy_cards.async_prepare_energy_panel(hass, page)

    assert prepared["_hero_unit"] == "kW"
    rendered = Template(prepared["_hero_template"], hass).async_render(parse_result=False)
    assert rendered == "2.50"


def test_history_axis_labels_read_in_kwh_not_kw() -> None:
    """Every bucket is an hour's change in kWh, so the axis reads kWh.

    A two-digit peak keeps its trailing "h": the renderer sizes the gutter to
    the label instead of capping at a fixed character count.
    """
    from custom_components.divoom_times_gate.units import format_auto

    assert format_auto(3.6, "kWh") == "3.6kWh"
    assert format_auto(12.4, "kWh") == "12.4kWh"
    assert format_auto(0.0, "kWh") == "0.0kWh"


async def test_energy_history_axis_label_fits_a_two_digit_peak(hass) -> None:
    """The full "kWh" label reaches the right edge instead of losing its "h"."""
    from io import BytesIO

    from PIL import Image

    page = {
        "card": "energy_history",
        "unit": "kWh",
        "background": "#000000",
        "_solar_series": [12.4, 8.0, *[None] * 22],
        "_consumption_series": None,
    }

    gif, _ = graphs.render_energy_history(hass, page, "http://h/dispdata/s")

    # "12.4kWh" is 33px wide, so a fitted label lights pixels within a few of the
    # right edge. A label truncated to "12.4kW" would stop short of that.
    image = Image.open(BytesIO(gif)).convert("RGB")
    top_band = image.crop((SCREEN_SIZE - 4, 0, SCREEN_SIZE, 20))
    colours = {colour for _, colour in top_band.getcolors(maxcolors=100000)}
    assert colours != {(0, 0, 0)}


def test_history_consumption_colour_matches_the_house_hero() -> None:
    """The house screen draws consumption in white, so the history line agrees."""
    history = presets.build_energy_preset(
        energy.parse_sources({"energy_sources": [FLAT_GRID, SOLAR]})
    )[4]

    assert history["consumption_color"] == "#FFFFFF"
