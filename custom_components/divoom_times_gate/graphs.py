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

from .cards import _blend, _encode_gif, _rgb, draw_glyph_text
from .const import DEFAULT_DEVICE_FONT, DEFAULT_LABEL_FONT, SCREEN_SIZE
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
    prepared["_footer_totals"] = await _footer_totals(hass, page)
    if tpl := page.get("color_template"):
        try:
            prepared["color"] = str(Template(str(tpl), hass).async_render()).strip() or page.get(
                "color"
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("graph color_template failed: %s", err)
    return prepared


async def _footer_totals(hass: HomeAssistant, page: dict[str, Any]) -> dict[str, float]:
    """Read today's total for every footer slot that names a statistic.

    Gas and water meters count up forever, so their current state is a meter
    reading rather than what the house used today. Long-term statistics record
    the change per hour, which sums to today's usage. Read that here and bake
    it into the artwork; a slot the recorder has no statistics for falls back
    to a live poll of its entity.
    """
    stats = [
        str(slot["stat"])
        for slot in (page.get("footer_slots") or [])
        if isinstance(slot, dict) and slot.get("stat")
    ]
    if not stats:
        return {}
    from .energy import async_daily_totals

    try:
        return await async_daily_totals(hass, stats)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("graph footer statistics failed: %s", err)
        return {}


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
        draw_glyph_text(draw, (2, top), title[:20], _blend(background, color, 0.75), "pico_8", 2)
        top += 13
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
        draw_glyph_text(
            draw, (left + 4, top + height // 2 - 5), "no data", (120, 120, 120), "pico_8", 2
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
        axis_ink = _blend(background, "#FFFFFF", 0.55)
        draw_glyph_text(draw, (right + 2, top), format_auto(high, unit)[:6], axis_ink)
        draw_glyph_text(draw, (right + 2, bottom - 6), format_auto(low, unit)[:6], axis_ink)

    if page.get("x_labels"):
        label_ink = _blend(background, "#FFFFFF", 0.45)
        times = [dt_util.parse_datetime(t) for t in page.get("_times") or []]
        if times and all(times):
            for fraction in (0.0, 0.5, 1.0):
                index = min(len(times) - 1, int(fraction * (len(times) - 1)))
                when = dt_util.as_local(times[index])  # type: ignore[arg-type]
                text = when.strftime("%H")
                x = left + int(fraction * (width - 10))
                draw_glyph_text(draw, (x, bottom + 1), text, label_ink)

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
                    "font": int(page.get("font", DEFAULT_DEVICE_FONT)),
                    "TextWidth": SCREEN_SIZE - 4,
                    "Textheight": 16,
                    "speed": 50,
                    "align": int(page.get("align", 1)),
                    "color": color,
                    "update_time": int(page.get("update_time", 10)),
                    "TextString": url,
                }
            )

    _draw_footer_slots(hass, page, draw, items, poll_base, background, footer)

    return _encode_gif(img), items


def _draw_footer_slots(
    hass: HomeAssistant,
    page: dict[str, Any],
    draw: ImageDraw.ImageDraw,
    items: list[dict[str, Any]],
    poll_base: str,
    background: str,
    footer: int,
) -> None:
    """Fill the reserved footer band with up to two labelled values.

    Screen five of the energy preset uses this for gas and water, which have no
    place on the electricity screens but still deserve a corner.
    """
    slots = [slot for slot in (page.get("footer_slots") or []) if isinstance(slot, dict)][:2]
    if not slots or footer <= 0:
        return
    band_top = SCREEN_SIZE - footer
    draw.line([(0, band_top), (SCREEN_SIZE, band_top)], fill=_blend(background, "#FFFFFF", 0.2))
    totals = page.get("_footer_totals") or {}
    cell = SCREEN_SIZE // len(slots)
    for index, slot in enumerate(slots):
        slot_color = str(slot.get("color", "#FFFFFF"))
        x = index * cell
        if label := slot.get("name"):
            draw_glyph_text(
                draw,
                (x + 3, band_top + 3),
                str(label)[:10],
                _blend(background, slot_color, 0.75),
                "pico_8",
                1,
            )
        total = totals.get(str(slot["stat"])) if slot.get("stat") else None
        if total is not None:
            unit = str(slot.get("unit") or "")
            # A litre reads as a whole number; cubic metres and kilowatt hours
            # move slowly enough that a decimal still says something.
            text = f"{total:.0f}" if unit == "L" else f"{total:.1f}"
            if unit:
                text = f"{text} {unit}"
            draw_glyph_text(
                draw,
                (x + 3, band_top + 12),
                text,
                _blend(background, slot_color, 1.0),
                "pico_8",
                2,
            )
            continue
        entity_id = str(slot.get("entity_id") or "")
        if template := slot.get("value_template"):
            key = hashlib.md5(str(template).encode()).hexdigest()[:12]
            secret = poll_base.rsplit("/", 1)[-1]
            register_value_template(hass, secret, key, str(template))
            url = f"{poll_base.replace('/dispdata/', '/dispdata_tpl/')}/{key}"
        elif entity_id:
            register_allowed_entity(hass, entity_id)
            url = f"{poll_base}/{quote(entity_id)}"
        else:
            continue
        items.append(
            {
                "TextId": 10 + index,
                "type": 23,
                "x": x + 2,
                "y": band_top + 14,
                "dir": 0,
                "font": int(slot.get("font", DEFAULT_LABEL_FONT)),
                "TextWidth": cell - 4,
                "Textheight": 14,
                "speed": 50,
                "align": 1,
                "color": slot_color,
                "update_time": int(slot.get("update_time", page.get("update_time", 10))),
                "TextString": url,
            }
        )
