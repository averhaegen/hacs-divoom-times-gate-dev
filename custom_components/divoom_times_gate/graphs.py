"""The ``graph`` card: a 128x128 chart drawn from recorder data or a template.

Rendering follows the same hybrid pattern as ``cards.render_sensor_grid``: HA
draws the chart into a background GIF the device fetches over HTTP, and the
current value rides along as a type-23 overlay the device polls itself. The
coordinator hashes the background, so a chart only re-sends when its pixels
actually change, not on every refresh tick.

Data comes from one of three sources, checked in this order:

``data_template``
    A Jinja template rendering to a list of numbers, or a list of mappings
    with a ``price``/``value``/``state`` key and an optional ``time``. This is
    how forward-looking series work, for example the ``prices`` attribute of
    an entso-e day-ahead sensor, which no recorder holds yet.
``statistic_id`` / ``entity_id`` with statistics
    Long-term statistics, the same source the HA energy dashboard reads, so
    the numbers match what the user sees there.
``entity_id`` without statistics
    Raw state history, for sensors that carry no ``state_class``.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import logging
from typing import Any
from urllib.parse import quote

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util
from PIL import Image, ImageDraw

from .cards import _blend, _encode_gif, _label_font, _rgb
from .const import SCREEN_SIZE
from .dispdata import register_allowed_entity, register_value_template
from .units import as_float, format_auto

_LOGGER = logging.getLogger(__name__)

DEFAULT_COLOR = "#FFB300"
DEFAULT_NEGATIVE_COLOR = "#4ADE80"
DEFAULT_BACKGROUND = "#000000"
AXIS_WIDTH = 24  # right-hand gutter for y-axis labels
XLABEL_HEIGHT = 9  # bottom strip for hour labels
STAT_TYPES = ("mean", "change", "min", "max", "sum", "state")


def _series_from_template(rendered: Any) -> tuple[list[float], list[datetime]]:
    """Pull ``(values, times)`` out of a rendered ``data_template``."""
    if not isinstance(rendered, (list, tuple)):
        raise ValueError("graph data_template must render to a list")
    values: list[float] = []
    times: list[datetime] = []
    for point in rendered:
        if isinstance(point, dict):
            raw = next(
                (point[key] for key in ("price", "value", "state", "y") if key in point),
                None,
            )
            when = point.get("time") or point.get("start") or point.get("x")
            if when is not None and (parsed := dt_util.parse_datetime(str(when))) is not None:
                times.append(parsed)
        else:
            raw = point
        if (number := as_float(raw)) is not None:
            values.append(number)
    if len(times) != len(values):
        times = []
    return values, times


async def _series_from_statistics(
    hass: HomeAssistant,
    statistic_id: str,
    start: datetime,
    end: datetime,
    period: str,
    stat_type: str,
) -> tuple[list[float], list[datetime]]:
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.statistics import statistics_during_period

    rows = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        {statistic_id},
        period,
        None,
        {stat_type},
    )
    values: list[float] = []
    times: list[datetime] = []
    for row in rows.get(statistic_id, []):
        if (number := as_float(row.get(stat_type))) is None:
            continue
        values.append(number)
        if (when := row.get("start")) is not None:
            times.append(dt_util.utc_from_timestamp(float(when)))
    if len(times) != len(values):
        times = []
    return values, times


async def _series_from_history(
    hass: HomeAssistant, entity_id: str, start: datetime, end: datetime
) -> tuple[list[float], list[datetime]]:
    from homeassistant.components.recorder import get_instance, history

    states = await get_instance(hass).async_add_executor_job(
        history.state_changes_during_period, hass, start, end, entity_id, True
    )
    values: list[float] = []
    times: list[datetime] = []
    for state in states.get(entity_id, []):
        if (number := as_float(state.state)) is None:
            continue
        values.append(number)
        times.append(state.last_updated)
    return values, times


def _resample(values: list[float], columns: int) -> list[float]:
    """Average ``values`` down (or stretch them up) to exactly ``columns``."""
    if not values or columns <= 0:
        return []
    if len(values) <= columns:
        # Stretch: repeat each sample so the chart spans the full width.
        return [values[min(len(values) - 1, i * len(values) // columns)] for i in range(columns)]
    out: list[float] = []
    for i in range(columns):
        lo = i * len(values) // columns
        hi = max(lo + 1, (i + 1) * len(values) // columns)
        bucket = values[lo:hi]
        out.append(sum(bucket) / len(bucket))
    return out


async def async_prepare_graph(hass: HomeAssistant, page: dict[str, Any]) -> dict[str, Any]:
    """Fetch the series on the event loop and attach it to the page.

    Recorder queries and template rendering both belong on the loop, so the
    executor-side renderer only ever sees plain numbers.
    """
    hours = float(page.get("hours", 24))
    end = dt_util.utcnow()
    start = end - timedelta(hours=hours)
    values: list[float] = []
    times: list[datetime] = []

    if template := page.get("data_template"):
        values, times = _series_from_template(Template(str(template), hass).async_render())
    else:
        statistic_id = str(page.get("statistic_id") or page.get("entity_id") or "")
        if not statistic_id:
            raise ValueError("graph card needs entity_id, statistic_id or data_template")
        stat_type = str(page.get("stat_type", "mean")).lower()
        if stat_type not in STAT_TYPES:
            raise ValueError(f"graph: unknown stat_type {stat_type!r}")
        period = str(page.get("period") or ("5minute" if hours <= 26 else "hour"))
        values, times = await _series_from_statistics(
            hass, statistic_id, start, end, period, stat_type
        )
        if not values and "." in statistic_id:
            # No long-term statistics for this sensor: fall back to raw history.
            values, times = await _series_from_history(hass, statistic_id, start, end)

    prepared = {**page, "_values": values, "_times": [t.isoformat() for t in times]}
    if tpl := page.get("color_template"):
        try:
            prepared["color"] = str(Template(str(tpl), hass).async_render()).strip() or page.get(
                "color"
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("graph color_template failed: %s", err)
    return prepared


def _axis_bounds(page: dict[str, Any], values: list[float]) -> tuple[float, float]:
    low = min(values)
    high = max(values)
    if str(page.get("baseline", "auto")).lower() == "zero" or low < 0 < high:
        low = min(low, 0.0)
        high = max(high, 0.0)
    if (fixed := as_float(page.get("y_min"))) is not None:
        low = fixed
    if (fixed := as_float(page.get("y_max"))) is not None:
        high = fixed
    if high - low < 1e-9:
        # A flat series still needs a range, otherwise every point maps to one row.
        pad = max(abs(high) * 0.1, 1.0)
        low, high = low - pad, high + pad
    return low, high


def render_graph(
    hass: HomeAssistant,
    page: dict[str, Any],
    poll_base: str,
) -> tuple[bytes, list[dict[str, Any]]]:
    """Render a graph card into ``(background_gif_bytes, overlay_items)``.

    Page schema::

        page_type: card
        card: graph
        entity_id: sensor.house_power   # or statistic_id, or data_template
        hours: 24                       # window, ignored for data_template
        stat_type: mean                 # mean | change | min | max | sum | state
        style: area                     # area | line | bar
        color: "#FFB300"
        negative_color: "#4ADE80"       # values below zero
        title: Verbruik                 # baked into the background
        unit: W                         # drives the axis label formatting
        axis: true                      # right-hand min/max labels
        marker: 24                      # highlight this column index
        value: true                     # live value overlay (type-23)
        value_entity: sensor.house_power
        footer_height: 0                # rows reserved at the bottom
    """
    values: list[float] = [float(v) for v in page.get("_values") or []]
    background = str(page.get("background") or DEFAULT_BACKGROUND)
    color = str(page.get("color") or DEFAULT_COLOR)
    negative_color = str(page.get("negative_color") or DEFAULT_NEGATIVE_COLOR)
    style = str(page.get("style", "area")).lower()
    if style not in ("area", "line", "bar"):
        raise ValueError(f"graph: unknown style {style!r}")

    img = Image.new("RGB", (SCREEN_SIZE, SCREEN_SIZE), background)
    draw = ImageDraw.Draw(img)
    items: list[dict[str, Any]] = []

    title = str(page.get("title") or "")
    show_value = bool(page.get("value", True))
    top = 2
    if title:
        draw.text((2, top), title[:20], font=_label_font(10), fill=_blend(background, color, 0.75))
        top += 12
    if show_value:
        top += 18  # room for the overlay value item drawn by the device

    footer = int(page.get("footer_height", 0))
    show_axis = bool(page.get("axis", True))
    left = 1
    right = SCREEN_SIZE - (AXIS_WIDTH if show_axis else 1)
    bottom = SCREEN_SIZE - footer - (XLABEL_HEIGHT if page.get("x_labels") else 1)
    width = max(1, right - left)
    height = max(1, bottom - top)

    if not values:
        draw.text(
            (left + 4, top + height // 2 - 5),
            "no data",
            font=_label_font(10),
            fill=(120, 120, 120),
        )
        return _encode_gif(img), items

    columns = _resample(values, width)
    low, high = _axis_bounds(page, columns)
    span = high - low

    def to_y(value: float) -> int:
        ratio = (value - low) / span
        return int(bottom - 1 - max(0.0, min(1.0, ratio)) * (height - 1))

    zero_y = to_y(0.0) if low < 0 < high else bottom - 1
    positive = _rgb(color)
    negative = _rgb(negative_color)

    previous: tuple[int, int] | None = None
    for index, value in enumerate(columns):
        x = left + index
        y = to_y(value)
        ink = positive if value >= 0 else negative
        if style == "line":
            if previous is not None:
                draw.line([previous, (x, y)], fill=ink)
            else:
                draw.point((x, y), fill=ink)
            previous = (x, y)
        elif style == "bar" and index % 2:
            continue  # 1px gap between bars
        else:
            y0, y1 = sorted((y, zero_y))
            draw.rectangle([x, y0, x, y1], fill=ink)

    if low < 0 < high:
        draw.line([(left, zero_y), (right - 1, zero_y)], fill=_blend(background, "#FFFFFF", 0.35))

    if (marker := page.get("marker")) is not None:
        # Highlight one column, e.g. the current hour on a forward price curve.
        position = int(marker) * width // max(1, len(values))
        marker_x = left + max(0, min(width - 1, position))
        draw.line([(marker_x, top), (marker_x, bottom - 1)], fill=_rgb("#FFFFFF"))

    unit = page.get("unit")
    if show_axis:
        axis_font = _label_font(9)
        axis_ink = _blend(background, "#FFFFFF", 0.55)
        draw.text((right + 2, top), format_auto(high, unit)[:6], font=axis_font, fill=axis_ink)
        draw.text(
            (right + 2, bottom - 9), format_auto(low, unit)[:6], font=axis_font, fill=axis_ink
        )

    if page.get("x_labels"):
        label_font = _label_font(8)
        label_ink = _blend(background, "#FFFFFF", 0.45)
        times = [dt_util.parse_datetime(t) for t in page.get("_times") or []]
        if times and all(times):
            for fraction in (0.0, 0.5, 1.0):
                index = min(len(times) - 1, int(fraction * (len(times) - 1)))
                when = dt_util.as_local(times[index])  # type: ignore[arg-type]
                text = when.strftime("%H")
                x = left + int(fraction * (width - 10))
                draw.text((x, bottom + 1), text, font=label_font, fill=label_ink)

    if show_value:
        entity_id = str(page.get("value_entity") or page.get("entity_id") or "")
        value_y = top - 18
        if template := page.get("value_template"):
            key = hashlib.md5(str(template).encode()).hexdigest()[:12]
            secret = poll_base.rsplit("/", 1)[-1]
            register_value_template(hass, secret, key, str(template))
            url = f"{poll_base.replace('/dispdata/', '/dispdata_tpl/')}/{key}"
        elif entity_id:
            register_allowed_entity(hass, entity_id)
            url = f"{poll_base}/{quote(entity_id)}"
        else:
            url = ""
        if url:
            items.append(
                {
                    "TextId": 1,
                    "type": 23,
                    "x": 2,
                    "y": max(0, value_y),
                    "dir": 0,
                    "font": int(page.get("font", 4)),
                    "TextWidth": SCREEN_SIZE - 4,
                    "Textheight": 16,
                    "speed": 50,
                    "align": int(page.get("align", 1)),
                    "color": color,
                    "update_time": int(page.get("update_time", 10)),
                    "TextString": url,
                }
            )

    return _encode_gif(img), items
