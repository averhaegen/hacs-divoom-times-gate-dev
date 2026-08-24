"""Energy panels: four purpose-built 128x128 layouts for the energy preset.

Each mode draws its own background and hands the live numbers to the device as
type-23 overlays, so the panel repaints only when the artwork changes while the
figures keep ticking on the device's own poll.

Modes:
  ``price``          current price large, with a min-to-max bar marking where it sits
  ``power``          house load large, one line of grid totals, gas and water below
  ``battery``        state of charge bar, percentage large, watts with direction
  ``solar``          current production large, today's yield below, day curve behind
  ``solar_battery``  solar on top with a goal bar, battery below with an SoC icon
                     and a bipolar power bar
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any
from urllib.parse import quote

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
from PIL import Image, ImageDraw

from .cards import _blend, _encode_gif, _hex, _rgb, draw_pixel_text, pixel_text_size
from .const import (
    ENERGY_COLORS,
    ENERGY_HERO_CHAR_WIDTH,
    ENERGY_HERO_FONT,
    ENERGY_HERO_HEIGHT,
    ENERGY_ROW_CHAR_WIDTH,
    ENERGY_ROW_FONT,
    ENERGY_ROW_HEIGHT,
    SCREEN_SIZE,
)
from .dispdata import register_allowed_entity, register_value_template
from .graphs import _draw_footer_slots, _footer_totals
from .mdi import draw_icon
from .units import as_float, format_energy, format_price, quantize_fraction

_LOGGER = logging.getLogger(__name__)

MODES = ("price", "power", "battery", "solar", "solar_battery")

# The gap between a number and the unit baked beside it. One pixel, because the
# device font already leaves a right side bearing inside the last digit's cell
# and anything wider reads as a space.
_UNIT_GAP = 1


async def async_prepare_energy_panel(
    hass: HomeAssistant, page: dict[str, Any]
) -> dict[str, Any]:
    """Resolve on-loop work: today's totals and any template-valued extras.

    Runs before the executor-side renderer because reading states and rendering
    templates both belong on the event loop.
    """
    mode = str(page.get("mode", "price")).lower()
    if mode not in MODES:
        raise ValueError(f"energy_panel: unknown mode {mode!r}")
    prepared = dict(page)

    stats = [
        page.get(key)
        for key in ("import_stat", "export_stat", "solar_stat")
        if page.get(key)
    ]
    if stats:
        from .energy import async_daily_totals

        try:
            prepared["_totals"] = await async_daily_totals(hass, [str(s) for s in stats])
        except Exception as err:  # noqa: BLE001 - recorder may be absent
            _LOGGER.debug("energy_panel daily totals unavailable: %s", err)
            prepared["_totals"] = {}
    else:
        prepared["_totals"] = {}

    # The house screen carries the gas and water footer, so resolve its totals
    # the same way the price graph does. `_footer_totals` reads today's change
    # for every slot that names a statistic and leaves the rest to a live poll.
    if page.get("footer_slots"):
        try:
            prepared["_footer_totals"] = await _footer_totals(hass, page)
        except Exception as err:  # noqa: BLE001 - recorder may be absent
            _LOGGER.debug("energy_panel footer totals unavailable: %s", err)
            prepared["_footer_totals"] = {}
    for key in ("price_min", "price_max", "price_now", "goal"):
        if template := page.get(f"{key}_template"):
            try:
                prepared[key] = as_float(Template(str(template), hass).async_render())
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("energy_panel %s_template failed: %s", key, err)
    for key in ("cheapest_time", "priciest_time"):
        if template := page.get(f"{key}_template"):
            try:
                rendered = Template(str(template), hass).async_render()
                prepared[key] = str(rendered or "").strip()
            except Exception as err:  # noqa: BLE001 - a malformed list draws nothing
                _LOGGER.debug("energy_panel %s_template failed: %s", key, err)
                prepared[key] = ""
    for key in ("battery_power", "solar_power", "house_power"):
        if entity := page.get(f"{key}_entity"):
            prepared[f"_{key}"] = as_float(
                (state := hass.states.get(str(entity))) and state.state
            )
    if entity := page.get("entity_id"):
        prepared["_current"] = as_float(
            (state := hass.states.get(str(entity))) and state.state
        )
    if entity := page.get("battery_soc"):
        prepared["_battery_soc"] = as_float(
            (state := hass.states.get(str(entity))) and state.state
        )
        # A battery-only merged screen draws the state of charge as its hero and
        # its bar, so resolve `_current` from the SoC sensor even when no page
        # entity_id points at it. Solar keeps `_current` for its own hero.
        if mode == "solar_battery" and not (
            page.get("solar_stat") or page.get("solar_power_entity")
        ):
            prepared["_current"] = prepared["_battery_soc"]

    if mode in ("solar", "solar_battery"):
        stat = str(page.get("solar_stat") or page.get("entity_id") or "")
        from .energy import async_day_curve

        try:
            prepared["_curve"] = await async_day_curve(hass, stat)
        except Exception as err:  # noqa: BLE001 - recorder may be absent
            _LOGGER.debug("energy_panel day curve unavailable: %s", err)
            prepared["_curve"] = []

    if mode == "solar_battery" and page.get("battery_power_entity"):
        # The bipolar bar needs its charging and discharging ends. Read them
        # once here from long-term statistics; a page override wins so a user
        # can still pin the range by hand.
        from .energy import async_power_range

        try:
            low, high = await async_power_range(
                hass,
                str(page["battery_power_entity"]),
                prepared.get("_battery_power"),
            )
        except Exception as err:  # noqa: BLE001 - recorder may be absent
            _LOGGER.debug("energy_panel power range unavailable: %s", err)
            low, high = -1000.0, 1000.0
        prepared["_power_min"] = as_float(page.get("power_min"), low)
        prepared["_power_max"] = as_float(page.get("power_max"), high)

    _prepare_overlay_templates(hass, prepared, mode)
    return prepared


def _inner(expression: str) -> str:
    """The body of a Jinja expression, so it can be wrapped in another."""
    text = str(expression).strip()
    if text.startswith("{{") and text.endswith("}}"):
        text = text[2:-2].strip()
    return text or "0"


def _unit_of(hass: HomeAssistant, entity_id: str | None) -> str:
    if not entity_id:
        return ""
    state = hass.states.get(str(entity_id))
    return str(state.attributes.get("unit_of_measurement") or "") if state else ""


def _kilowatts(source: str, unit: str) -> str:
    """A Jinja body converting ``source`` to kilowatts with two decimals.

    Every panel reads in kW so the figures compare at a glance, and two
    decimals keep a 40W standby load visible without the digits outgrowing the
    panel. The unit is fixed, so it is baked into the artwork once instead of
    following whatever the sensor happens to report.
    """
    scales = {"w": 0.001, "kw": 1.0, "mw": 1000.0}
    # `mW` and `MW` differ only in case and by a factor of a billion, so match
    # the milliwatt spelling exactly before folding case for the rest.
    scale = 1e-6 if unit.strip() == "mW" else scales.get(unit.strip().lower(), 0.001)
    return f"'%.2f' | format((({source}) | float(0)) * {scale:.9f})"


def _prepare_overlay_templates(
    hass: HomeAssistant, page: dict[str, Any], mode: str
) -> None:
    """Build digit-only templates for the values the device renders itself.

    Font 184 draws digits, a dot and a handful of capitals, and the dispdata
    view appends a state's own unit, so polling an entity directly would show
    `0.184k` for `0.184 EUR/kWh`. Render the number here instead and leave the
    unit to the artwork beside it.
    """
    entity = page.get("entity_id")
    source = _inner(str(page["value_template"])) if page.get("value_template") else (
        f"states('{entity}')" if entity else "0"
    )
    unit = _unit_of(hass, entity)

    if mode == "solar_battery":
        # The merged screen picks its own hero from the sources present so each
        # fallback shows the figure it draws, rather than trusting a page-level
        # entity_id to point at the right sensor. Solar wins when it exists; a
        # battery-only home reads its state of charge instead.
        if page.get("solar_stat") or page.get("solar_power_entity"):
            if solar_entity := (page.get("solar_power_entity") or entity):
                source = f"states('{solar_entity}')"
                unit = _unit_of(hass, str(solar_entity))
        elif soc_entity := page.get("battery_soc"):
            source = f"states('{soc_entity}')"
            unit = ""

    if mode == "price":
        page["_hero_template"] = f"{{{{ '%.3f' | format(({source}) | float(0)) }}}}"
        page["_hero_unit"] = ""
        page["_hero_chars"] = 5
    elif mode == "battery" or (
        mode == "solar_battery"
        and not (page.get("solar_stat") or page.get("solar_power_entity"))
    ):
        # A battery-only merged screen falls back to the battery layout, so its
        # hero is the state of charge, not a kW figure.
        page["_hero_template"] = f"{{{{ ({source}) | float(0) | round(0) | int }}}}"
        page["_hero_unit"] = "%"
        page["_hero_chars"] = 3
    else:
        page["_hero_template"] = f"{{{{ {_kilowatts(source, unit)} }}}}"
        page["_hero_unit"] = "kW"
        page["_hero_chars"] = 5

    rows: dict[str, str] = {}
    for key, entity_key in (
        ("import", "import_entity"),
        ("export", "export_entity"),
        ("power", "power_entity"),
    ):
        if row_entity := page.get(entity_key):
            body = _kilowatts(f"states('{row_entity}')", _unit_of(hass, row_entity))
            if key == "power":
                # The word beside it already says which way the energy flows,
                # so a minus sign here would only read as a second opinion.
                body = f"{body} | replace('-', '')"
            rows[key] = f"{{{{ {body} }}}}"
    page["_row_templates"] = rows

    # The merged screen shows the battery percentage as a live overlay, but font
    # 184 has no percent glyph, so poll a digit-only value and bake the "%".
    if soc_entity := page.get("battery_soc"):
        page["_soc_template"] = (
            f"{{{{ states('{soc_entity}') | float(0) | round(0) | int }}}}"
        )


def _poll_item(
    hass: HomeAssistant,
    items: list[dict[str, Any]],
    poll_base: str,
    *,
    text_id: int,
    entity_id: str | None,
    value_template: str | None,
    x: int,
    y: int,
    width: int,
    font: int,
    color: str,
    align: int = 2,
    height: int = 16,
    update_time: int = 10,
) -> None:
    """Append a type-23 overlay the device polls for one value."""
    if value_template:
        key = hashlib.md5(str(value_template).encode()).hexdigest()[:12]
        secret = poll_base.rsplit("/", 1)[-1]
        register_value_template(hass, secret, key, str(value_template))
        url = f"{poll_base.replace('/dispdata/', '/dispdata_tpl/')}/{key}"
    elif entity_id:
        register_allowed_entity(hass, entity_id)
        url = f"{poll_base}/{quote(entity_id)}"
    else:
        return
    items.append(
        {
            "TextId": text_id,
            "type": 23,
            "x": x,
            "y": y,
            "dir": 0,
            "font": font,
            "TextWidth": max(16, width),
            "Textheight": height,
            "speed": 50,
            "align": align,
            "color": color,
            "update_time": update_time,
            "TextString": url,
        }
    )


def _text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    color: Any,
    scale: int = 2,
    align: str = "left",
) -> None:
    """Draw a baked-in artwork label. See ``cards.draw_pixel_text``."""
    draw_pixel_text(draw, xy, text, color, scale, align)


def _value_pair_width(unit: str, chars: int, char_width: int) -> int:
    """The pixel width of a ``_value`` number-and-unit pair.

    Hoist the same width `_value` uses internally so a caller can lay the pair
    out as part of a wider group, such as centring it beside the battery icon.
    """
    unit_width = pixel_text_size(unit, 2)[0] if unit else 0
    gap = _UNIT_GAP if unit else 0
    number_width = max(16, chars * char_width)
    return number_width + gap + unit_width


def _value(
    hass: HomeAssistant,
    draw: ImageDraw.ImageDraw,
    items: list[dict[str, Any]],
    poll_base: str,
    background: str,
    *,
    text_id: int,
    y: int,
    color: str,
    unit: str,
    chars: int,
    font: int,
    height: int,
    char_width: int,
    entity_id: str | None = None,
    value_template: str | None = None,
    right: int | None = None,
    left: int | None = None,
) -> None:
    """Place one live figure with the unit baked beside it.

    Every device font that carries a decimal point carries no ``k``, so the
    unit has to be artwork, and the number has to land right against it.

    The device decides where the text sits inside the item box and does not
    right-align the way `align: 3` suggests: a short value drifts to the middle
    of whatever box it is given (docs/API.md §4.10). So the box is cut to the
    number itself, ``chars`` cells wide and no wider, which pins the value
    beside its unit however the firmware chooses to place it. A value shorter
    than ``chars`` drifts by half the spare cells, a few pixels rather than the
    width of the panel.

    ``right`` anchors the pair's right edge instead of centring it, and
    ``left`` anchors the number's left edge, which lets a caller sit the pair
    beside another element such as the battery icon.
    """
    unit_width, unit_height = pixel_text_size(unit, 2) if unit else (0, 0)
    gap = _UNIT_GAP if unit else 0
    number_width = max(16, chars * char_width)
    if left is not None:
        edge = left + number_width
    elif right is None:
        start = max(0, (SCREEN_SIZE - (number_width + gap + unit_width)) // 2)
        edge = start + number_width
    else:
        edge = right - gap - unit_width
    _poll_item(
        hass,
        items,
        poll_base,
        text_id=text_id,
        entity_id=entity_id,
        value_template=value_template,
        x=max(0, edge - number_width),
        y=y,
        width=number_width,
        font=font,
        color=color,
        align=3,
        height=height,
    )
    if unit:
        # Sit the unit on the number's baseline. `height` is the font's own cell
        # height, so the digits fill the box and the unit drops to its foot.
        _text(
            draw,
            (edge + gap, y + max(0, height - unit_height)),
            unit,
            _blend(background, color, 0.75),
            2,
        )


def _hero(
    hass: HomeAssistant,
    page: dict[str, Any],
    draw: ImageDraw.ImageDraw,
    items: list[dict[str, Any]],
    poll_base: str,
    background: str,
    *,
    y: int,
    color: str,
) -> None:
    """The one figure the panel exists for, with its unit beside it."""
    _value(
        hass,
        draw,
        items,
        poll_base,
        background,
        text_id=1,
        y=y,
        color=color,
        unit=str(page.get("_hero_unit") or ""),
        chars=int(page.get("_hero_chars") or 5),
        font=int(page.get("font", ENERGY_HERO_FONT)),
        height=ENERGY_HERO_HEIGHT,
        char_width=ENERGY_HERO_CHAR_WIDTH,
        entity_id=page.get("entity_id"),
        value_template=page.get("_hero_template") or page.get("value_template"),
    )


def _draw_price(
    hass: HomeAssistant,
    page: dict[str, Any],
    draw: ImageDraw.ImageDraw,
    items: list[dict[str, Any]],
    poll_base: str,
    background: str,
) -> None:
    """Current price on top, a min-to-max bar with a marker underneath."""
    low = as_float(page.get("price_min"))
    high = as_float(page.get("price_max"))
    now = as_float(page.get("_current"))
    cheap = str(page.get("cheap_color", "#4ADE80"))
    dear = str(page.get("expensive_color", "#EF4444"))

    # Without a real range there is nothing honest to draw: a bar from 0.000 to
    # 0.000 reads like a price rather than like missing data.
    known = low is not None and high is not None and high > low
    position = 0.5
    if known and now is not None:
        # Snap to the bar's own resolution. Anything finer only rewrites the
        # artwork without moving a pixel. Keep the fine 1/50 step the marker used
        # before so the position still reads exactly on this hourly data.
        assert low is not None and high is not None
        position = quantize_fraction(now, low, high, step=0.02)
    value_color = _hex(_blend(cheap, dear, position)) if known else "#FFFFFF"

    _text(draw, (64, 6), str(page.get("name", "Price")), _blend(background, "#FFFFFF", 0.55), 2, "center")
    _hero(hass, page, draw, items, poll_base, background, y=28, color=value_color)
    _text(draw, (64, 54), str(page.get("unit", "EUR/kWh")), _blend(background, "#FFFFFF", 0.45), 2, "center")

    if not known:
        _text(draw, (64, 92), "no range today", _blend(background, "#FFFFFF", 0.35), 2, "center")
        return

    bar_x, bar_y, bar_w, bar_h = 12, 84, SCREEN_SIZE - 24, 10
    for step in range(bar_w):
        color = _blend(cheap, dear, step / max(1, bar_w - 1))
        draw.line([(bar_x + step, bar_y), (bar_x + step, bar_y + bar_h)], fill=color)
    marker = bar_x + int(position * (bar_w - 1))
    draw.rectangle(
        [marker - 1, bar_y - 4, marker + 1, bar_y + bar_h + 4], fill="#FFFFFF"
    )
    _text(draw, (bar_x, bar_y + bar_h + 6), format_price(low or 0.0), _rgb(cheap), 2)
    _text(draw, (bar_x + bar_w, bar_y + bar_h + 6), format_price(high or 0.0), _rgb(dear), 2, "right")

    # Bake the hour of the cheapest and priciest price under its figure. These
    # are baked artwork, not overlays, and a missing or malformed price list
    # leaves both empty so nothing extra draws.
    cheapest = str(page.get("cheapest_time") or "")
    priciest = str(page.get("priciest_time") or "")
    time_y = bar_y + bar_h + 6 + ENERGY_ROW_HEIGHT + 2
    if cheapest:
        _text(draw, (bar_x, time_y), cheapest, _blend(background, cheap, 0.7), 1)
    if priciest:
        _text(draw, (bar_x + bar_w, time_y), priciest, _blend(background, dear, 0.7), 1, "right")


def _draw_grid_totals(
    draw: ImageDraw.ImageDraw,
    background: str,
    *,
    y: int,
    import_total: float | None,
    export_total: float | None,
    import_color: str,
    export_color: str,
) -> None:
    """Bake one line of today's import and export, each behind its arrow.

    These are daily totals from long-term statistics, not live values, so bake
    them as artwork rather than polling. A down arrow marks import, an up arrow
    marks export, each in its own colour. Omit the side the recorder has no
    total for so a grid-in-only home still reads as one clean line.
    """
    gap = 3  # arrow to number
    span = 8  # import block to export block
    scale = 2
    blocks: list[tuple[str, str, str]] = []
    if import_total is not None:
        blocks.append(("arrow-down-bold", f"{import_total:.1f}", import_color))
    if export_total is not None:
        blocks.append(("arrow-up-bold", f"{export_total:.1f}", export_color))
    if not blocks:
        return

    # Size the arrow so its visible glyph matches the figure height beside it,
    # not a round number. The webfont draws a bold arrow at about three quarters
    # of its point size, so scale the point size up by four thirds to land the
    # glyph on the same optical line. The whole line still has to fit 128px:
    # a down arrow, a figure, an up arrow, a figure and the trailing unit.
    text_h = pixel_text_size("0", scale)[1]
    icon = round(text_h * 4 / 3)
    suffix = "kWh today"
    suffix_w = pixel_text_size(suffix, 1)[0]
    widths = [icon + gap + pixel_text_size(text, scale)[0] for _, text, _ in blocks]
    total_w = sum(widths) + span * (len(blocks) - 1) + gap + suffix_w
    x = max(0, (SCREEN_SIZE - total_w) // 2)
    for (name, text, color), width in zip(blocks, widths, strict=True):
        draw_icon(draw, name, (x, y), icon, _rgb(color))
        _text(draw, (x + icon + gap, y), text, _rgb(color), scale)
        x += width + span
    # The unit trails the last number, sat on its baseline and dimmed so the
    # figures stay the thing the eye lands on.
    _text(draw, (x - span + gap, y + text_h - pixel_text_size(suffix, 1)[1]), suffix, _blend(background, "#FFFFFF", 0.5), 1)


def _draw_power(
    hass: HomeAssistant,
    page: dict[str, Any],
    draw: ImageDraw.ImageDraw,
    items: list[dict[str, Any]],
    poll_base: str,
    background: str,
) -> None:
    """House load large, one line of grid totals, then the gas and water band."""
    import_color = str(page.get("import_color", ENERGY_COLORS["grid_import"]))
    export_color = str(page.get("export_color", ENERGY_COLORS["grid_export"]))
    totals: dict[str, float] = page.get("_totals") or {}

    _text(draw, (64, 6), str(page.get("name", "House")), _blend(background, "#FFFFFF", 0.55), 2, "center")
    # The live house load is the hero and stays a polled overlay. The freed rows
    # give it and the footer room, so sit it high and let the line breathe below.
    _hero(hass, page, draw, items, poll_base, background, y=34, color="#FFFFFF")

    import_total = totals.get(str(page["import_stat"])) if page.get("import_stat") else None
    export_total = totals.get(str(page["export_stat"])) if page.get("export_stat") else None
    _draw_grid_totals(
        draw,
        background,
        y=68,
        import_total=import_total,
        export_total=export_total,
        import_color=import_color,
        export_color=export_color,
    )

    # Gas and water live here now, drawn by the same footer renderer the price
    # graph used. An empty footer draws no band, so a home with neither still
    # reads clean.
    footer = int(page.get("footer_height", 0))
    _draw_footer_slots(hass, page, draw, items, poll_base, background, footer)


def _draw_battery(
    hass: HomeAssistant,
    page: dict[str, Any],
    draw: ImageDraw.ImageDraw,
    items: list[dict[str, Any]],
    poll_base: str,
    background: str,
) -> None:
    """A charge bar, the percentage large, and the rate with its direction."""
    soc = as_float(page.get("_current"), 0.0) or 0.0
    rate = as_float(page.get("_battery_power"), 0.0) or 0.0
    # Home Assistant reads a positive battery rate as discharge, so the battery
    # is charging while the rate is negative. `invert_power` flips a sensor
    # that reports the other way round.
    charging = rate > 0 if page.get("invert_power") else rate < 0
    color = ENERGY_COLORS["battery_in"] if charging else ENERGY_COLORS["battery_out"]
    color = str(page.get("charge_color", color) if charging else page.get("discharge_color", color))

    _text(draw, (64, 4), str(page.get("name", "Battery")), _blend(background, "#FFFFFF", 0.55), 2, "center")

    bar_x, bar_y, bar_w, bar_h = 14, 24, SCREEN_SIZE - 28, 18
    draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], outline=_blend(background, color, 0.5))
    # Snap to 10% steps. The bar is the artwork, so a step per percent re-sent
    # the whole panel for a change nobody can see at arm's length.
    filled = int(bar_w * quantize_fraction(soc, 0.0, 100.0, step=0.1))
    if filled > 1:
        draw.rectangle([bar_x + 1, bar_y + 1, bar_x + filled - 1, bar_y + bar_h - 1], fill=_rgb(color))

    _hero(hass, page, draw, items, poll_base, background, y=48, color=color)
    _text(draw, (64, 84), "charging" if charging else "discharging", _blend(background, color, 0.7), 2, "center")
    _value(
        hass,
        draw,
        items,
        poll_base,
        background,
        text_id=2,
        y=104,
        color=color,
        unit="kW",
        chars=5,
        font=int(page.get("row_font", ENERGY_ROW_FONT)),
        height=ENERGY_ROW_HEIGHT,
        char_width=ENERGY_ROW_CHAR_WIDTH,
        entity_id=None
        if (page.get("_row_templates") or {}).get("power")
        else (str(page["power_entity"]) if page.get("power_entity") else None),
        value_template=(page.get("_row_templates") or {}).get("power"),
    )

def _draw_solar(
    hass: HomeAssistant,
    page: dict[str, Any],
    draw: ImageDraw.ImageDraw,
    items: list[dict[str, Any]],
    poll_base: str,
    background: str,
) -> None:
    """Current production large, today's yield below, day curve behind."""
    color = str(page.get("color", ENERGY_COLORS["solar"]))
    totals: dict[str, float] = page.get("_totals") or {}
    curve = [v for v in (page.get("_curve") or []) if isinstance(v, int | float)]

    if curve:
        peak = max(max(curve), 1.0)
        step = SCREEN_SIZE / len(curve)
        faint = _blend(background, color, 0.3)
        for index, value in enumerate(curve):
            height = int((value / peak) * 40)
            if height <= 0:
                continue
            x0 = int(index * step)
            x1 = max(x0, int((index + 1) * step) - 1)
            draw.rectangle([x0, SCREEN_SIZE - height, x1, SCREEN_SIZE], fill=faint)

    _text(draw, (64, 6), str(page.get("name", "Solar")), _blend(background, "#FFFFFF", 0.55), 2, "center")
    _hero(hass, page, draw, items, poll_base, background, y=28, color=color)
    produced = totals.get(str(page.get("solar_stat"))) if page.get("solar_stat") else None
    drew_goal = _draw_goal_bar(draw, page, background, color, produced, x=12, y=62, w=SCREEN_SIZE - 24, h=6)
    if not drew_goal and produced is not None:
        _text(draw, (64, 66), f"{format_energy(produced)} today", _rgb(color), 2, "center")


def _draw_goal_bar(
    draw: ImageDraw.ImageDraw,
    page: dict[str, Any],
    background: str,
    color: str,
    produced: float | None,
    *,
    x: int,
    y: int,
    w: int,
    h: int,
) -> bool:
    """Draw the solar goal bar and its caption, or return False for no goal.

    Fill is today's yield as a fraction of the goal. A cumulative kWh figure
    only creeps upward, so the fill is not banded: it changes little enough per
    tick to stay cheap to repaint, and banding would hide honest progress.
    Returns False when no goal resolves so the caller keeps the plain caption.
    """
    goal = as_float(page.get("goal"))
    if not goal or goal <= 0:
        return False
    yield_today = produced or 0.0
    fraction = min(1.0, max(0.0, yield_today / goal))
    draw.rectangle([x, y, x + w, y + h], outline=_blend(background, color, 0.5))
    filled = int(w * fraction)
    if filled > 1:
        draw.rectangle([x + 1, y + 1, x + filled - 1, y + h - 1], fill=_rgb(color))
    caption = f"{yield_today:.1f} / {goal:g} kWh today"
    _text(draw, (64, y + h + 3), caption, _rgb(color), 1, "center")
    return True


def _battery_band_icon(soc: float, charging: bool) -> str:
    """The MDI battery icon for a state of charge, banded to the nearest 10%.

    The icon is baked artwork that swaps image, so banding to a decile holds it
    still until the charge crosses a band. MDI spells a full battery ``battery``
    and an empty one ``battery-outline`` rather than ``battery-100``/``-0``, so
    map the ends onto the names that actually exist.
    """
    band = max(0, min(100, round(soc / 10) * 10))
    if charging:
        if band <= 0:
            return "mdi:battery-charging-outline"
        return f"mdi:battery-charging-{band}"
    if band >= 100:
        return "mdi:battery"
    if band <= 0:
        return "mdi:battery-outline"
    return f"mdi:battery-{band}"


def _draw_power_bar(
    draw: ImageDraw.ImageDraw,
    page: dict[str, Any],
    background: str,
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    rate: float,
    charging: bool,
    color: str,
) -> None:
    """A bipolar bar: charging fills left of a marked zero, discharging right.

    The zero point sits where 0 W falls inside the charging-to-discharging
    range. Both the zero marker and the fill snap to the bar's own resolution so
    a live wattage does not repaint the artwork on every reading.
    """
    low = as_float(page.get("_power_min"), -1000.0) or -1000.0
    high = as_float(page.get("_power_max"), 1000.0) or 1000.0
    if high <= low:  # never divide by zero, even on a flat or missing range
        high = low + 1.0
    zero_px = x + int(quantize_fraction(0.0, low, high, step=0.1) * w)
    rate_px = x + int(quantize_fraction(rate, low, high, step=0.1) * w)

    draw.rectangle([x, y, x + w, y + h], outline=_blend(background, "#FFFFFF", 0.4))
    lo_px, hi_px = sorted((zero_px, rate_px))
    if hi_px - lo_px >= 1:
        draw.rectangle([lo_px, y + 1, hi_px, y + h - 1], fill=_rgb(color))
    # The zero marker rides above and below the bar so it reads against the fill.
    draw.rectangle([zero_px - 1, y - 2, zero_px + 1, y + h + 2], fill=_blend(background, "#FFFFFF", 0.85))


def _draw_solar_battery(
    hass: HomeAssistant,
    page: dict[str, Any],
    draw: ImageDraw.ImageDraw,
    items: list[dict[str, Any]],
    poll_base: str,
    background: str,
) -> None:
    """Solar on top with its goal bar, battery below with an SoC icon and bar.

    Falls back to the full-height solar layout when there is no battery, the
    full-height battery layout when there is no solar, and draws nothing when
    neither side has a source.
    """
    has_solar = bool(page.get("solar_stat") or page.get("solar_power_entity"))
    has_battery = bool(page.get("battery_soc") or page.get("battery_power_entity"))
    if has_solar and not has_battery:
        _draw_solar(hass, page, draw, items, poll_base, background)
        return
    if has_battery and not has_solar:
        _draw_battery(hass, page, draw, items, poll_base, background)
        return
    if not has_solar and not has_battery:
        return

    solar_color = str(page.get("color", ENERGY_COLORS["solar"]))
    totals: dict[str, float] = page.get("_totals") or {}
    curve = [v for v in (page.get("_curve") or []) if isinstance(v, int | float)]

    # The dim day curve sits behind the solar half only. Keep it short so its
    # top stays below the goal caption at y=42, or the number would cross the
    # silhouette. That leaves the bar and its caption reading as one unit.
    solar_bottom = 60
    curve_height = 10
    if curve:
        peak = max(max(curve), 1.0)
        step = SCREEN_SIZE / len(curve)
        faint = _blend(background, solar_color, 0.3)
        for index, value in enumerate(curve):
            height = int((value / peak) * curve_height)
            if height <= 0:
                continue
            x0 = int(index * step)
            x1 = max(x0, int((index + 1) * step) - 1)
            draw.rectangle([x0, solar_bottom - height, x1, solar_bottom], fill=faint)

    _text(draw, (64, 1), str(page.get("name", "Energy")), _blend(background, "#FFFFFF", 0.5), 1, "center")
    _hero(hass, page, draw, items, poll_base, background, y=12, color=solar_color)
    produced = totals.get(str(page.get("solar_stat"))) if page.get("solar_stat") else None
    drew_goal = _draw_goal_bar(draw, page, background, solar_color, produced, x=12, y=34, w=SCREEN_SIZE - 24, h=5)
    if not drew_goal and produced is not None:
        _text(draw, (64, 42), f"{format_energy(produced)} today", _rgb(solar_color), 1, "center")

    draw.line([(6, solar_bottom), (SCREEN_SIZE - 6, solar_bottom)], fill=_blend(background, "#FFFFFF", 0.25))

    rate = as_float(page.get("_battery_power"), 0.0) or 0.0
    soc = as_float(page.get("_battery_soc"), 0.0) or 0.0
    charging = rate > 0 if page.get("invert_power") else rate < 0
    bat_color = ENERGY_COLORS["battery_in"] if charging else ENERGY_COLORS["battery_out"]
    bat_color = str(page.get("charge_color", bat_color) if charging else page.get("discharge_color", bat_color))

    # Treat the icon and the percentage as one group and centre it, so the icon
    # sits beside the figure it describes instead of drifting to the far edge.
    # The band icon carries the charge and the direction, which frees the row of
    # the charging/discharging word the standalone battery screen still spends.
    icon_size = 26
    icon_y = 66
    icon_gap = 6
    soc_font = int(page.get("row_font", ENERGY_ROW_FONT))
    pair_width = _value_pair_width("%", 3, ENERGY_ROW_CHAR_WIDTH)
    group_width = icon_size + icon_gap + pair_width
    group_x = max(0, (SCREEN_SIZE - group_width) // 2)
    draw_icon(draw, _battery_band_icon(soc, charging), (group_x, icon_y), icon_size, _rgb(bat_color))

    # Live percentage beside the icon, sat on the icon's vertical centre. Font
    # 184 has no percent glyph, so poll a digit-only value and bake the "%".
    _value(
        hass,
        draw,
        items,
        poll_base,
        background,
        text_id=2,
        y=icon_y + (icon_size - ENERGY_ROW_HEIGHT) // 2,
        color=bat_color,
        unit="%",
        chars=3,
        font=soc_font,
        height=ENERGY_ROW_HEIGHT,
        char_width=ENERGY_ROW_CHAR_WIDTH,
        entity_id=None if page.get("_soc_template") else page.get("battery_soc"),
        value_template=page.get("_soc_template"),
        left=group_x + icon_size + icon_gap,
    )

    # Live power value above the bar. The sign is stripped (font 184 has no
    # minus), so colour and fill direction carry charging versus discharging.
    _value(
        hass,
        draw,
        items,
        poll_base,
        background,
        text_id=3,
        y=94,
        color=bat_color,
        unit="kW",
        chars=5,
        font=int(page.get("row_font", ENERGY_ROW_FONT)),
        height=ENERGY_ROW_HEIGHT,
        char_width=ENERGY_ROW_CHAR_WIDTH,
        entity_id=None
        if (page.get("_row_templates") or {}).get("power")
        else (str(page["power_entity"]) if page.get("power_entity") else None),
        value_template=(page.get("_row_templates") or {}).get("power"),
    )

    _draw_power_bar(
        draw,
        page,
        background,
        x=12,
        y=114,
        w=SCREEN_SIZE - 24,
        h=10,
        rate=rate,
        charging=charging,
        color=bat_color,
    )


_DRAWERS = {
    "price": _draw_price,
    "power": _draw_power,
    "battery": _draw_battery,
    "solar": _draw_solar,
    "solar_battery": _draw_solar_battery,
}


def render_energy_panel(
    hass: HomeAssistant, page: dict[str, Any], poll_base: str
) -> tuple[bytes, list[dict[str, Any]]]:
    """Render one energy panel, returning its background GIF and overlays."""
    mode = str(page.get("mode", "price")).lower()
    drawer = _DRAWERS.get(mode)
    if drawer is None:
        raise ValueError(f"energy_panel: unknown mode {mode!r}")

    background = str(page.get("background", "#000000"))
    image = Image.new("RGB", (SCREEN_SIZE, SCREEN_SIZE), background)
    draw = ImageDraw.Draw(image)
    items: list[dict[str, Any]] = []
    drawer(hass, page, draw, items, poll_base, background)
    return _encode_gif(image), items
