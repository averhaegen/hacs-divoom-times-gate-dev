"""Energy panels: four purpose-built 128x128 layouts for the energy preset.

Each mode draws its own background and hands the live numbers to the device as
type-23 overlays, so the panel repaints only when the artwork changes while the
figures keep ticking on the device's own poll.

Modes:
  ``price``    current price large, with a min-to-max bar marking where it sits
  ``power``    house load large, import and export below with today's totals
  ``battery``  state of charge bar, percentage large, watts with direction
  ``solar``    current production large, today's yield below, day curve behind
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any
from urllib.parse import quote

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
from PIL import Image, ImageDraw, ImageFont

from .cards import _blend, _encode_gif, _hex, _rgb
from .const import (
    ENERGY_COLORS,
    ENERGY_HERO_FONT,
    ENERGY_HERO_HEIGHT,
    ENERGY_ROW_FONT,
    ENERGY_ROW_HEIGHT,
    SCREEN_SIZE,
)
from .dispdata import register_allowed_entity, register_value_template
from .units import as_float, format_energy, format_price

_LOGGER = logging.getLogger(__name__)

MODES = ("price", "power", "battery", "solar")

# Pixel Operator SC Bold (CC0, Jayvee Enaguas) draws the baked-in artwork
# labels. It is a pixel face, so it stays crisp at these sizes where a hinted
# desktop font would blur, and the bold weight holds up against the panel's
# bloom better than the regular one. The superscripts it lacks fall back to
# plain digits.
_TTF_PATH = Path(__file__).parent / "fonts" / "PixelOperatorSC-Bold.ttf"
_TTF_SUBSTITUTES = str.maketrans({"\u00b3": "3", "\u00b2": "2"})
_TTF_CACHE: dict[int, ImageFont.FreeTypeFont] = {}


def _ttf_font(size: int) -> ImageFont.FreeTypeFont:
    if size not in _TTF_CACHE:
        _TTF_CACHE[size] = ImageFont.truetype(_TTF_PATH, size)
    return _TTF_CACHE[size]


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

    for key in ("price_min", "price_max", "price_now"):
        if template := page.get(f"{key}_template"):
            try:
                prepared[key] = as_float(Template(str(template), hass).async_render())
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning("energy_panel %s_template failed: %s", key, err)
    for key in ("battery_power", "solar_power", "house_power"):
        if entity := page.get(f"{key}_entity"):
            prepared[f"_{key}"] = as_float(
                (state := hass.states.get(str(entity))) and state.state
            )
    if entity := page.get("entity_id"):
        prepared["_current"] = as_float(
            (state := hass.states.get(str(entity))) and state.state
        )

    if mode == "solar":
        stat = str(page.get("solar_stat") or page.get("entity_id") or "")
        from .energy import async_day_curve

        try:
            prepared["_curve"] = await async_day_curve(hass, stat)
        except Exception as err:  # noqa: BLE001 - recorder may be absent
            _LOGGER.debug("energy_panel day curve unavailable: %s", err)
            prepared["_curve"] = []

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


def _watts(source: str, unit: str) -> str:
    """A Jinja body converting ``source`` to whole watts."""
    scale = " * 1000" if unit.strip().lower() == "kw" else ""
    return f"(({source}){scale}) | float(0) | round(0) | int"


def _prepare_overlay_templates(
    hass: HomeAssistant, page: dict[str, Any], mode: str
) -> None:
    """Build digit-only templates for the values the device renders itself.

    Font 246 draws `0123456789.` and nothing else, and the dispdata view
    appends a state's own unit, so polling an entity directly would show
    `0.184k` for `0.184 EUR/kWh`. Render the number here instead and leave the
    unit to the artwork. The row font (248) does carry `%`, `W` and a sign, so
    a row keeps its unit in the polled text.
    """
    entity = page.get("entity_id")
    source = _inner(str(page["value_template"])) if page.get("value_template") else (
        f"states('{entity}')" if entity else "0"
    )
    unit = _unit_of(hass, entity)

    if mode == "price":
        page["_hero_template"] = f"{{{{ '%.3f' | format(({source}) | float(0)) }}}}"
        page["_hero_unit"] = ""
    elif mode == "battery":
        page["_hero_template"] = f"{{{{ ({source}) | float(0) | round(0) | int }}}}"
        page["_hero_unit"] = "%"
    else:
        page["_hero_template"] = f"{{{{ {_watts(source, unit)} }}}}"
        page["_hero_unit"] = "W"

    rows: dict[str, str] = {}
    for key, entity_key in (
        ("import", "import_entity"),
        ("export", "export_entity"),
        ("power", "power_entity"),
    ):
        if row_entity := page.get(entity_key):
            body = _watts(f"states('{row_entity}')", _unit_of(hass, row_entity))
            if key == "power":
                # The word beside it already says which way the energy flows,
                # so a minus sign here would only read as a second opinion.
                body = f"{body} | abs"
            rows[key] = f"{{{{ {body} }}}}W"
    page["_row_templates"] = rows


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
    """Draw a baked-in label in Pixel Operator SC.

    Only the artwork uses this. The live figures stay type-23 overlays the
    device renders in its own firmware fonts, so they are untouched.

    ``scale`` keeps the old bitmap-font call sites working: one step is 8px of
    font size, which puts scale 2 within a pixel of the pico_8 metrics the
    layouts were positioned against. Anti-aliasing is off (``fontmode = "1"``)
    because a grey edge pixel smears on an LED panel.

    ``xy`` is the top-left of the inked box unless ``align`` moves it:
    ``center`` treats x as the midpoint, ``right`` as the right edge.
    """
    font = _ttf_font(8 * max(1, int(scale)))
    text = str(text).translate(_TTF_SUBSTITUTES)
    box = font.getbbox(text)
    left, top, width = int(box[0]), int(box[1]), int(box[2]) - int(box[0])
    x, y = xy
    if align == "center":
        x -= width // 2
    elif align == "right":
        x -= width
    draw.fontmode = "1"
    draw.text((x - left, y - top), text, font=font, fill=color)


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
    """The one figure the panel exists for, with its unit beside it.

    The device renders the number itself in font 246 (18x22), so it may only
    contain digits and a dot. The unit is baked into the artwork to its right,
    on the same line, because that is how the pair gets read out loud.
    """
    unit = str(page.get("_hero_unit") or "")
    # A unit needs the right-hand gutter, so the number ends where it starts.
    # Without one the number simply owns the full width.
    number_width = SCREEN_SIZE - 28 if unit else SCREEN_SIZE
    _poll_item(
        hass,
        items,
        poll_base,
        text_id=1,
        entity_id=page.get("entity_id"),
        value_template=page.get("_hero_template") or page.get("value_template"),
        x=0,
        y=y,
        width=number_width,
        font=int(page.get("font", ENERGY_HERO_FONT)),
        color=color,
        align=3 if unit else 2,
        height=ENERGY_HERO_HEIGHT,
    )
    if unit:
        _text(draw, (SCREEN_SIZE - 24, y + 6), unit, _blend(background, color, 0.75), 2)


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
        # Quantise to the bar's own resolution. Anything finer only rewrites
        # the artwork without moving a pixel.
        assert low is not None and high is not None
        raw = max(0.0, min(1.0, (now - low) / (high - low)))
        position = round(raw * 50) / 50
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


def _draw_power(
    hass: HomeAssistant,
    page: dict[str, Any],
    draw: ImageDraw.ImageDraw,
    items: list[dict[str, Any]],
    poll_base: str,
    background: str,
) -> None:
    """House load large, then an import row and an export row with day totals."""
    import_color = str(page.get("import_color", ENERGY_COLORS["grid_import"]))
    export_color = str(page.get("export_color", ENERGY_COLORS["grid_export"]))
    totals: dict[str, float] = page.get("_totals") or {}
    row_templates: dict[str, str] = page.get("_row_templates") or {}

    _text(draw, (64, 4), str(page.get("name", "House")), _blend(background, "#FFFFFF", 0.55), 2, "center")
    _hero(hass, page, draw, items, poll_base, background, y=22, color="#FFFFFF")

    rows = (
        ("import", import_color, page.get("import_entity"), page.get("import_stat"), 60),
        ("export", export_color, page.get("export_entity"), page.get("export_stat"), 92),
    )
    for index, (label, color, entity, stat, y) in enumerate(rows):
        draw.rectangle([0, y, 3, y + 26], fill=_rgb(color))
        _text(draw, (8, y), label.upper(), _rgb(color), 2)
        _poll_item(
            hass,
            items,
            poll_base,
            text_id=2 + index,
            entity_id=None if row_templates.get(label) else (str(entity) if entity else None),
            value_template=row_templates.get(label),
            x=64,
            y=y + 2,
            width=60,
            font=int(page.get("row_font", ENERGY_ROW_FONT)),
            color=color,
            align=3,
            height=ENERGY_ROW_HEIGHT,
        )
        total = totals.get(str(stat)) if stat else None
        if total is not None:
            _text(draw, (124, y + 18), f"{format_energy(total)} today", _blend(background, color, 0.75), 1, "right")


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
    # Quantise to 10% steps. The bar is the artwork, so a step per percent
    # re-sent the whole panel for a change nobody can see at arm's length.
    steps = round(max(0.0, min(100.0, soc)) / 10)
    filled = int(bar_w * steps / 10)
    if filled > 1:
        draw.rectangle([bar_x + 1, bar_y + 1, bar_x + filled - 1, bar_y + bar_h - 1], fill=_rgb(color))

    _hero(hass, page, draw, items, poll_base, background, y=48, color=color)
    _text(draw, (64, 84), "charging" if charging else "discharging", _blend(background, color, 0.7), 2, "center")
    _poll_item(
        hass,
        items,
        poll_base,
        text_id=2,
        entity_id=None
        if (page.get("_row_templates") or {}).get("power")
        else (str(page["power_entity"]) if page.get("power_entity") else None),
        value_template=(page.get("_row_templates") or {}).get("power"),
        x=0,
        y=104,
        width=SCREEN_SIZE,
        font=int(page.get("row_font", ENERGY_ROW_FONT)),
        color=color,
        align=2,
        height=ENERGY_ROW_HEIGHT,
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
    if produced is not None:
        _text(draw, (64, 66), f"{format_energy(produced)} today", _rgb(color), 2, "center")


_DRAWERS = {
    "price": _draw_price,
    "power": _draw_power,
    "battery": _draw_battery,
    "solar": _draw_solar,
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
