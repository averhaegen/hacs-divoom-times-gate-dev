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
from typing import Any
from urllib.parse import quote

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
from PIL import Image, ImageDraw

from .cards import _blend, _encode_gif, _hex, _rgb, draw_glyph_text
from .const import ENERGY_COLORS, ENERGY_FONT, ENERGY_LABEL_FONT, SCREEN_SIZE
from .dispdata import register_allowed_entity, register_value_template
from .units import as_float, format_energy, format_price

_LOGGER = logging.getLogger(__name__)

MODES = ("price", "power", "battery", "solar")


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
    return prepared


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
            "Textheight": 16,
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
    """Draw a baked-in label with a hard-edged bitmap font.

    Everything drawn into the artwork uses this rather than Pillow's default
    font, which anti-aliases and turns to mush on the panel.
    """
    draw_glyph_text(draw, xy, text, color, "pico_8", scale, align)


def _draw_price(
    hass: HomeAssistant,
    page: dict[str, Any],
    draw: ImageDraw.ImageDraw,
    items: list[dict[str, Any]],
    poll_base: str,
    background: str,
) -> None:
    """Current price on top, a min-to-max bar with a marker underneath."""
    low = as_float(page.get("price_min"), 0.0) or 0.0
    high = as_float(page.get("price_max"), 0.0) or 0.0
    now = as_float(page.get("_current"))
    cheap = str(page.get("cheap_color", "#4ADE80"))
    dear = str(page.get("expensive_color", "#EF4444"))

    span = high - low
    position = 0.5 if span <= 0 or now is None else max(0.0, min(1.0, (now - low) / span))
    value_color = _hex(_blend(cheap, dear, position))

    _text(draw, (64, 6), str(page.get("name", "Price")), _blend(background, "#FFFFFF", 0.55), 2, "center")
    _poll_item(
        hass,
        items,
        poll_base,
        text_id=1,
        entity_id=page.get("entity_id"),
        value_template=page.get("value_template"),
        x=0,
        y=28,
        width=SCREEN_SIZE,
        font=int(page.get("font", ENERGY_FONT)),
        color=value_color,
        align=2,
    )
    _text(draw, (64, 58), str(page.get("unit", "EUR/kWh")), _blend(background, "#FFFFFF", 0.45), 2, "center")

    bar_x, bar_y, bar_w, bar_h = 12, 84, SCREEN_SIZE - 24, 10
    for step in range(bar_w):
        color = _blend(cheap, dear, step / max(1, bar_w - 1))
        draw.line([(bar_x + step, bar_y), (bar_x + step, bar_y + bar_h)], fill=color)
    marker = bar_x + int(position * (bar_w - 1))
    draw.rectangle(
        [marker - 1, bar_y - 4, marker + 1, bar_y + bar_h + 4], fill="#FFFFFF"
    )
    _text(draw, (bar_x, bar_y + bar_h + 6), format_price(low), _rgb(cheap), 2)
    _text(draw, (bar_x + bar_w, bar_y + bar_h + 6), format_price(high), _rgb(dear), 2, "right")


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

    _text(draw, (64, 4), str(page.get("name", "House")), _blend(background, "#FFFFFF", 0.55), 2, "center")
    _poll_item(
        hass,
        items,
        poll_base,
        text_id=1,
        entity_id=page.get("entity_id"),
        value_template=page.get("value_template"),
        x=0,
        y=20,
        width=SCREEN_SIZE,
        font=int(page.get("font", ENERGY_FONT)),
        color="#FFFFFF",
        align=2,
    )

    rows = (
        ("import", import_color, page.get("import_entity"), page.get("import_stat"), 62),
        ("export", export_color, page.get("export_entity"), page.get("export_stat"), 94),
    )
    for index, (label, color, entity, stat, y) in enumerate(rows):
        draw.rectangle([0, y - 6, 3, y + 22], fill=_rgb(color))
        _text(draw, (8, y - 6), label.upper(), _rgb(color), 2)
        _poll_item(
            hass,
            items,
            poll_base,
            text_id=2 + index,
            entity_id=str(entity) if entity else None,
            value_template=None,
            x=60,
            y=y - 8,
            width=64,
            font=int(page.get("row_font", ENERGY_LABEL_FONT)),
            color=color,
            align=3,
        )
        total = totals.get(str(stat)) if stat else None
        if total is not None:
            _text(draw, (124, y + 10), f"{format_energy(total)} today", _blend(background, color, 0.75), 2, "right")


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

    bar_x, bar_y, bar_w, bar_h = 14, 22, SCREEN_SIZE - 28, 18
    draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], outline=_blend(background, color, 0.5))
    filled = int(bar_w * max(0.0, min(100.0, soc)) / 100)
    if filled > 1:
        draw.rectangle([bar_x + 1, bar_y + 1, bar_x + filled - 1, bar_y + bar_h - 1], fill=_rgb(color))

    _poll_item(
        hass,
        items,
        poll_base,
        text_id=1,
        entity_id=page.get("entity_id"),
        value_template=page.get("value_template"),
        x=0,
        y=52,
        width=SCREEN_SIZE,
        font=int(page.get("font", ENERGY_FONT)),
        color=color,
        align=2,
    )
    _text(draw, (64, 88), "charging" if charging else "discharging", _blend(background, color, 0.7), 2, "center")
    _poll_item(
        hass,
        items,
        poll_base,
        text_id=2,
        entity_id=str(page["power_entity"]) if page.get("power_entity") else None,
        value_template=None,
        x=0,
        y=102,
        width=SCREEN_SIZE,
        font=int(page.get("row_font", ENERGY_LABEL_FONT)),
        color=color,
        align=2,
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
            height = int((value / peak) * 56)
            if height <= 0:
                continue
            x0 = int(index * step)
            x1 = max(x0, int((index + 1) * step) - 1)
            draw.rectangle([x0, SCREEN_SIZE - height, x1, SCREEN_SIZE], fill=faint)

    _text(draw, (64, 6), str(page.get("name", "Solar")), _blend(background, "#FFFFFF", 0.55), 2, "center")
    _poll_item(
        hass,
        items,
        poll_base,
        text_id=1,
        entity_id=page.get("entity_id"),
        value_template=page.get("value_template"),
        x=0,
        y=30,
        width=SCREEN_SIZE,
        font=int(page.get("font", ENERGY_FONT)),
        color=color,
        align=2,
    )
    produced = totals.get(str(page.get("solar_stat"))) if page.get("solar_stat") else None
    if produced is not None:
        _text(draw, (64, 74), f"{format_energy(produced)} today", _rgb(color), 2, "center")


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
