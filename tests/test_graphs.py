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
    format_axis,
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


async def test_render_graph_narrows_the_value_block_to_fit_a_baked_unit(hass) -> None:
    """The unit is artwork, so the polled string stays bare digits.

    Serving the entity's own state appends its unit, which a device font
    without lowercase glyphs renders as stray characters.
    """
    _, plain = _render(
        hass, {"_values": [1, 2, 3], "entity_id": "sensor.price", "value": True}
    )
    _, with_unit = _render(
        hass,
        {
            "_values": [1, 2, 3],
            "entity_id": "sensor.price",
            "value": True,
            "value_unit": "EUR/kWh",
        },
    )

    assert with_unit[0]["TextWidth"] < plain[0]["TextWidth"]
    assert with_unit[0]["align"] == 5  # right, so the number meets its unit


def test_format_axis_drops_a_price_to_two_decimals() -> None:
    """An axis label only says how high the plot reaches, so it reads short."""
    assert format_axis(0.318, "EUR/kWh") == "0.32"
    # Every other unit keeps the formatting it already had.
    assert format_axis(1500.0, "W") == format_auto(1500.0, "W")


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


def test_hour_marks_sit_in_the_gap_before_the_hour() -> None:
    """A rule takes the gap pixel between two bars, not the bar itself."""
    from custom_components.divoom_times_gate.graphs import _hour_marks

    marks = _hour_marks(list(range(24)), left=1, width=120)

    assert [index for index, _x in marks] == [0, 6, 12, 18]
    # 120px over 24 columns is 5px an hour, so hour 6 starts 30px in and its
    # rule takes the pixel before that. Hour 0 has no gap to its left.
    assert [x for _index, x in marks] == [1, 30, 60, 90]


def test_window_bounds_static_starts_at_local_midnight() -> None:
    from homeassistant.util import dt as dt_util

    from custom_components.divoom_times_gate.graphs import _window_bounds

    now = dt_util.utcnow()
    start, end, mode = _window_bounds({"hours": 24, "window": "static"}, now)

    assert mode == "static"
    assert dt_util.as_local(start).hour == 0
    assert (end - start).total_seconds() == 24 * 3600


def test_window_bounds_rolling_ends_at_now() -> None:
    from homeassistant.util import dt as dt_util

    from custom_components.divoom_times_gate.graphs import _window_bounds

    now = dt_util.utcnow()
    start, end, mode = _window_bounds({"hours": 6}, now)

    assert mode == "rolling"
    assert end == now
    assert (end - start).total_seconds() == 6 * 3600


def test_window_bounds_reject_an_unknown_window() -> None:
    from homeassistant.util import dt as dt_util

    from custom_components.divoom_times_gate.graphs import _window_bounds

    with pytest.raises(ValueError, match="unknown window"):
        _window_bounds({"window": "sliding"}, dt_util.utcnow())


def test_trim_to_window_cuts_a_forecast_down_to_the_next_day() -> None:
    """A 48 hour price list draws 24 hours from the current hour."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    from custom_components.divoom_times_gate.graphs import _trim_to_window

    now = dt_util.utcnow()
    start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=4)
    times = [start + timedelta(hours=index) for index in range(48)]
    values = [float(index) for index in range(48)]

    kept_values, kept_times = _trim_to_window(values, times, {"hours": 24}, now)

    assert len(kept_values) == 24
    assert kept_times[0] == now.replace(minute=0, second=0, microsecond=0)


def test_trim_to_window_static_keeps_today_only() -> None:
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    from custom_components.divoom_times_gate.graphs import _trim_to_window

    now = dt_util.utcnow()
    midnight = dt_util.as_utc(dt_util.start_of_local_day(dt_util.as_local(now)))
    times = [midnight + timedelta(hours=index) for index in range(48)]
    values = [float(index) for index in range(48)]

    kept_values, kept_times = _trim_to_window(
        values, times, {"hours": 24, "window": "static"}, now
    )

    assert len(kept_values) == 24
    assert kept_times[0] == midnight
    assert dt_util.as_local(kept_times[-1]).hour == 23


def test_trim_to_window_leaves_a_series_without_timestamps_alone() -> None:
    from homeassistant.util import dt as dt_util

    from custom_components.divoom_times_gate.graphs import _trim_to_window

    values = [1.0, 2.0, 3.0]

    assert _trim_to_window(values, [], {"hours": 1}, dt_util.utcnow()) == (values, [])
