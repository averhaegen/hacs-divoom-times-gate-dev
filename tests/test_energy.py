"""Tests for energy discovery, the energy panels and the preset layer."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from custom_components.divoom_times_gate import energy, energy_cards, graphs, presets
from custom_components.divoom_times_gate.const import (
    CONF_ACTIVE_PRESET,
    CONF_PRESETS,
    CONF_SCREENS,
    DEFAULT_PRESET,
    ENERGY_PRESET,
)

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
    assert [s.get("mode") for s in screens[:4]] == ["price", "power", "battery", "solar"]
    assert screens[4]["card"] == "graph"
    assert screens[4]["footer_height"] == 32
    assert [slot["name"] for slot in screens[4]["footer_slots"]] == ["Gas", "Water"]


def test_build_energy_preset_blanks_missing_sources() -> None:
    screens = presets.build_energy_preset(energy.parse_sources({"energy_sources": [FLAT_GRID]}))

    assert screens[2] == {"page_type": "off"}
    assert screens[3] == {"page_type": "off"}
    assert screens[4]["footer_height"] == 0


def test_build_energy_preset_reads_a_statistic_only_gas_from_the_recorder() -> None:
    found = energy.parse_sources(
        {"energy_sources": [{"type": "gas", "stat_energy_from": "nhc2:abc_gasvolume"}]}
    )

    slot = presets.build_energy_preset(found)[4]["footer_slots"][0]

    assert slot["stat"] == "nhc2:abc_gasvolume"
    assert "entity_id" not in slot
    assert slot["unit"] == "m\u00b3"


async def test_graph_footer_totals_cover_statistic_only_slots(hass) -> None:
    page = {
        "card": "graph",
        "data_template": "[1, 2, 3]",
        "footer_height": 32,
        "footer_slots": [
            {"stat": "nhc2:abc_gasvolume", "name": "Gas", "unit": "m\u00b3"},
            {"entity_id": "sensor.water", "name": "Water"},
        ],
    }

    with patch(
        "custom_components.divoom_times_gate.energy.async_daily_totals",
        return_value={"nhc2:abc_gasvolume": 3.25},
    ) as totals:
        prepared = await graphs.async_prepare_graph(hass, page)

    assert totals.call_args[0][1] == ["nhc2:abc_gasvolume"]
    assert prepared["_footer_totals"] == {"nhc2:abc_gasvolume": 3.25}

    gif, items = graphs.render_graph(hass, prepared, "http://h/dispdata/secret")

    assert gif.startswith(b"GIF")
    # Only the water slot is polled; gas is drawn into the artwork.
    assert [item["TextId"] for item in items if item["TextId"] >= 10] == [11]


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
