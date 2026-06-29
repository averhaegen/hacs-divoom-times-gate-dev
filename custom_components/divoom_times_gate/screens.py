"""Config-driven screen rendering for the Times Gate.

A screen config is a dict. The 5 screens are configured as a list under the
``screens`` option. Each screen has a ``type``:

  * ``custom`` (default) — render a layout from templated values (Jinja2).
  * ``clock``            — show a native device clock face (``clock_id``).
  * ``off``              — black screen.

``custom`` screens pick a ``layout`` and supply Jinja2 ``{{ ... }}`` templates
for the text fields. Colors may be a ``[r,g,b]`` list, a ``#RRGGBB`` string, a
CSS color name, or ``"auto"`` (the layout decides based on the value).

This is intentionally close to the gickowtf/pixoo-homeassistant (MIT) approach:
templated component values rendered to an image.
"""
from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from homeassistant.core import HomeAssistant
from homeassistant.helpers import template as template_helper

from .const import SCREEN_SIZE as S

_LOGGER = logging.getLogger(__name__)

_FONT_CACHE: dict[int, ImageFont.FreeTypeFont] = {}

_CSS_COLORS = {
    "white": (255, 255, 255), "black": (0, 0, 0), "red": (255, 0, 0),
    "green": (0, 255, 0), "blue": (96, 165, 250), "yellow": (250, 204, 21),
    "orange": (255, 140, 0), "cyan": (0, 200, 255), "grey": (170, 170, 170),
    "gray": (170, 170, 170),
}


def _font(size: int) -> ImageFont.FreeTypeFont:
    if size not in _FONT_CACHE:
        try:
            _FONT_CACHE[size] = ImageFont.load_default(size)
        except TypeError:
            _FONT_CACHE[size] = ImageFont.load_default()
    return _FONT_CACHE[size]


def _render_template(hass: HomeAssistant, value: Any) -> str:
    """Render a Jinja2 template string against HA state. Non-strings pass through."""
    if not isinstance(value, str) or "{{" not in value and "{%" not in value:
        return "" if value is None else str(value)
    try:
        tpl = template_helper.Template(value, hass)
        return str(tpl.async_render())
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Template error in screen value %r: %s", value, err)
        return "ERR"


def _color(value: Any, default=(255, 255, 255)) -> tuple[int, int, int]:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return (int(value[0]), int(value[1]), int(value[2]))
    if isinstance(value, str):
        v = value.strip().lower()
        if v in _CSS_COLORS:
            return _CSS_COLORS[v]
        if v.startswith("#") and len(v) == 7:
            return (int(v[1:3], 16), int(v[3:5], 16), int(v[5:7], 16))
    return default


def _ctext(d: ImageDraw.ImageDraw, cx: int, y: int, text: str, size: int, fill) -> None:
    f = _font(size)
    bbox = d.textbbox((0, 0), text, font=f)
    d.text((cx - (bbox[2] - bbox[0]) / 2, y), text, font=f, fill=fill)


def _to_jpeg(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, "JPEG", quality=95)
    return buf.getvalue()


# --- layouts ----------------------------------------------------------------

def _layout_big(hass, cfg, d, color) -> None:
    """title (top) + big value (middle) + sub (bottom)."""
    title = _render_template(hass, cfg.get("title", ""))
    value = _render_template(hass, cfg.get("value", ""))
    sub = _render_template(hass, cfg.get("sub", ""))
    if title:
        _ctext(d, S // 2, 8, title, 13, (170, 170, 170))
    _ctext(d, S // 2, 40, value, int(cfg.get("value_size", 42)), color)
    if sub:
        _ctext(d, S // 2, 100, sub, 13, (255, 255, 255))


def _layout_dual(hass, cfg, d, color) -> None:
    """title + two labeled rows (label1/value1, label2/value2)."""
    title = _render_template(hass, cfg.get("title", ""))
    if title:
        _ctext(d, S // 2, 6, title, 13, (170, 170, 170))
    _ctext(d, S // 2, 26, _render_template(hass, cfg.get("value", "")), 22, (255, 255, 255))
    _ctext(d, S // 2, 52, _render_template(hass, cfg.get("sub", "")), 13, (170, 170, 170))
    d.line([16, 74, S - 16, 74], fill=(51, 51, 51))
    _ctext(d, S // 2, 80, _render_template(hass, cfg.get("value2", "")), 22, color)
    _ctext(d, S // 2, 108, _render_template(hass, cfg.get("sub2", "")), 12, (170, 170, 170))


def _layout_bar(hass, cfg, d, color) -> None:
    """title + big value + progress bar + sub. bar_pct is a template -> 0..100."""
    title = _render_template(hass, cfg.get("title", ""))
    value = _render_template(hass, cfg.get("value", ""))
    sub = _render_template(hass, cfg.get("sub", ""))
    if title:
        _ctext(d, S // 2, 8, title, 13, (170, 170, 170))
    _ctext(d, S // 2, 30, value, 46, color)
    try:
        pct = max(0.0, min(100.0, float(_render_template(hass, cfg.get("bar_pct", "0")))))
    except ValueError:
        pct = 0.0
    bx, by, bw, bh = 20, 84, 88, 12
    d.rectangle([bx, by, bx + bw, by + bh], outline=(85, 85, 85))
    d.rectangle([bx + 1, by + 1, bx + 1 + int((bw - 2) * pct / 100), by + bh - 1], fill=color)
    if sub:
        _ctext(d, S // 2, 102, sub, 13, (255, 255, 255))


_LAYOUTS = {"big": _layout_big, "dual": _layout_dual, "bar": _layout_bar}


def render_custom_screen(hass: HomeAssistant, cfg: dict[str, Any]) -> bytes:
    """Render one ``custom`` screen config to JPEG bytes."""
    color = cfg.get("border", "white")
    color = _color(color) if color != "auto" else _auto_color(hass, cfg)

    img = Image.new("RGB", (S, S), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([2, 2, S - 3, S - 3], outline=color, width=3)

    layout = _LAYOUTS.get(cfg.get("layout", "big"), _layout_big)
    layout(hass, cfg, d, color)
    return _to_jpeg(img)


def render_black() -> bytes:
    """A black 128x128 JPEG (for ``off`` screens)."""
    return _to_jpeg(Image.new("RGB", (S, S), (0, 0, 0)))


def _auto_color(hass: HomeAssistant, cfg: dict[str, Any]) -> tuple[int, int, int]:
    """Optional ``color_template`` -> color name/hex; else white."""
    if "color_template" in cfg:
        return _color(_render_template(hass, cfg["color_template"]))
    return (255, 255, 255)
