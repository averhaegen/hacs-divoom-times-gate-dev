"""Tests for the graph card renderer."""
from __future__ import annotations

from io import BytesIO

from PIL import Image
import pytest

from custom_components.divoom_times_gate.graphs import (
    _axis_bounds,
    _resample,
    _series_from_template,
    render_graph,
)
from custom_components.divoom_times_gate.units import (
    format_auto,
    format_energy,
    format_power,
    format_price,
)

POLL_BASE = "http://ha.local:8123/api/divoom_times_gate/dispdata/secret123"


def _render(hass, page):
    gif, items = render_graph(hass, page, POLL_BASE)
    image = Image.open(BytesIO(gif))
    return image, items


def test_resample_averages_down_to_the_column_count() -> None:
    assert _resample([0.0, 2.0, 4.0, 6.0], 2) == [1.0, 5.0]


def test_resample_stretches_a_short_series_across_the_width() -> None:
    assert _resample([1.0, 3.0], 4) == [1.0, 1.0, 3.0, 3.0]


def test_resample_of_an_empty_series_is_empty() -> None:
    assert _resample([], 10) == []


def test_axis_bounds_include_zero_when_the_series_crosses_it() -> None:
    assert _axis_bounds({}, [-5.0, 10.0]) == (-5.0, 10.0)


def test_axis_bounds_pad_a_flat_series() -> None:
    low, high = _axis_bounds({}, [7.0, 7.0])
    assert low < 7.0 < high


def test_axis_bounds_honour_fixed_limits() -> None:
    assert _axis_bounds({"y_min": 0, "y_max": 100}, [20.0, 30.0]) == (0.0, 100.0)


def test_series_from_template_reads_plain_numbers() -> None:
    values, times = _series_from_template([1, 2.5, "3"])
    assert values == [1.0, 2.5, 3.0]
    assert times == []


def test_series_from_template_reads_entsoe_price_points() -> None:
    values, times = _series_from_template(
        [
            {"time": "2026-08-23 00:00:00+02:00", "price": 0.14063},
            {"time": "2026-08-23 01:00:00+02:00", "price": 0.12},
        ]
    )
    assert values == [0.14063, 0.12]
    assert len(times) == 2


def test_series_from_template_rejects_a_non_list() -> None:
    with pytest.raises(ValueError, match="must render to a list"):
        _series_from_template("not a list")


async def test_render_graph_produces_a_128px_background(hass) -> None:
    image, items = _render(hass, {"_values": [1, 2, 3, 4], "value": False})
    assert image.size == (128, 128)
    assert items == []


async def test_render_graph_without_data_still_renders(hass) -> None:
    image, items = _render(hass, {"_values": [], "value": False})
    assert image.size == (128, 128)
    assert items == []


async def test_render_graph_rejects_an_unknown_style(hass) -> None:
    with pytest.raises(ValueError, match="unknown style"):
        render_graph(hass, {"_values": [1, 2], "style": "pie"}, POLL_BASE)


async def test_render_graph_emits_a_polling_overlay_for_the_current_value(hass) -> None:
    _, items = _render(
        hass,
        {"_values": [1, 2, 3], "entity_id": "sensor.house_power", "value": True},
    )
    assert len(items) == 1
    item = items[0]
    assert item["type"] == 23
    assert item["TextString"].endswith("/sensor.house_power")
    assert item["update_time"] == 10


async def test_render_graph_uses_a_value_template_endpoint_when_given_one(hass) -> None:
    _, items = _render(
        hass,
        {
            "_values": [1, 2, 3],
            "entity_id": "sensor.house_power",
            "value_template": "{{ 1 }}",
        },
    )
    assert "/dispdata_tpl/" in items[0]["TextString"]


async def test_render_graph_draws_negative_values_in_the_negative_colour(hass) -> None:
    image, _ = _render(
        hass,
        {
            "_values": [-100.0] * 8,
            "color": "#FF0000",
            "negative_color": "#00FF00",
            "value": False,
            "axis": False,
        },
    )
    colors = {color for _count, color in image.convert("RGB").getcolors(4096)}
    assert (0, 255, 0) in colors
    assert (255, 0, 0) not in colors


def test_format_power_switches_to_kilowatts_above_1000() -> None:
    assert format_power(950) == "950W"
    assert format_power(1500) == "1.5kW"
    assert format_power(1500, signed=True) == "+1.5kW"
    assert format_power(-1500) == "-1.5kW"


def test_format_price_keeps_three_decimals() -> None:
    assert format_price(0.1839) == "0.184"


def test_format_energy_drops_the_decimal_past_100() -> None:
    assert format_energy(9.25) == "9.2kWh"
    assert format_energy(120.4) == "120kWh"


def test_format_auto_picks_the_formatter_from_the_unit() -> None:
    assert format_auto(1500, "W") == "1.5kW"
    assert format_auto(2.5, "kW") == "2.5kW"
    assert format_auto(55, "%") == "55%"
    assert format_auto(0.184, "EUR/kWh") == "0.184"
