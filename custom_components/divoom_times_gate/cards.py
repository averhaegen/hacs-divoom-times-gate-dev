"""Card gallery: purpose-built 128x128 layouts (SPEC_CARD_GALLERY.md Tier 2).

The hybrid rendering pattern: HA renders the *background* (icons, labels,
frames) and serves it as a GIF the device fetches once; live values are
type-23 overlay items the device polls itself — value updates never repaint
the panel. The background only re-sends when its content hash changes
(config edits, state-dependent icon colors crossing a threshold).

v2.0 ships `sensor_grid`: 2-8 sensor slots, densest-fitting layout chosen by
count (see _layout_cells). The 8-slot ceiling is a design choice for
readability on 128px, not a device limit (TextId < 40 per docs/API.md §4.10).
"""
from __future__ import annotations

import hashlib
import logging
from io import BytesIO
from typing import Any
from urllib.parse import quote

from PIL import Image, ImageDraw, ImageFont

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template

from .const import NATIVE_KIND_TYPES, SCREEN_SIZE
from .dispdata import register_value_template
from .mdi import draw_icon, icon_for_state

_LOGGER = logging.getLogger(__name__)

MAX_SLOTS = 8
_LABEL_COLOR = (128, 128, 128)
_DEFAULT_VALUE_COLOR = "#FFFFFF"


def _label_font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size)
    except (AttributeError, OSError):
        return ImageFont.load_default()


def _layout_cells(count: int) -> list[tuple[int, int, int, int]]:
    """Cell rectangles (x, y, w, h) for ``count`` slots on a 128x128 canvas.

    2 → horizontal halves · 3-4 → quadrants · 5-6 → 2 cols x 3 rows ·
    7-8 → 2 cols x 4 rows. Unused trailing cells are simply left empty.
    """
    s = SCREEN_SIZE
    if count <= 2:
        return [(0, 0, s, s // 2), (0, s // 2, s, s // 2)]
    if count <= 4:
        h = s // 2
        return [(c % 2 * h, c // 2 * h, h, h) for c in range(4)]
    if count <= 6:
        w, h = s // 2, s // 3
        return [(c % 2 * w, c // 2 * h, w, h) for c in range(6)]
    w, h = s // 2, s // 4
    return [(c % 2 * w, c // 2 * h, w, h) for c in range(8)]


def _resolve_color(hass: HomeAssistant, slot: dict[str, Any]) -> str:
    """Slot icon/value colour: ``color_template`` (rendered) > ``color`` > white."""
    if tpl := slot.get("color_template"):
        try:
            return str(Template(str(tpl), hass).async_render()).strip() or _DEFAULT_VALUE_COLOR
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("sensor_grid color_template failed: %s", err)
    return str(slot.get("color", _DEFAULT_VALUE_COLOR))


def render_sensor_grid(
    hass: HomeAssistant,
    page: dict[str, Any],
    poll_base: str,
) -> tuple[bytes, list[dict[str, Any]]]:
    """Render a sensor_grid card.

    Returns ``(background_gif_bytes, overlay_items)``. ``poll_base`` is the
    dispdata URL prefix up to (and including) the secret, e.g.
    ``http://ha.local:8123/api/divoom_times_gate/dispdata/<secret>``.

    Page schema::

        page_type: card
        card: sensor_grid          # currently the only type
        layout: auto               # auto | list | grid
        header: time_short         # native element top-right in list layout
                                   # (any const.NATIVE_KIND_TYPES name, or "none")
        update_time: 10            # poll seconds, page-wide default
        slots:                     # 1-8 entries
          - entity_id: sensor.solar_power
            name: Solar            # label; defaults to the entity's name
            icon: mdi:solar-power  # defaults to entity icon / device_class
            color: "#FFB300"       # icon + value colour
            color_template: ...    # optional template overriding `color`
            value_template: ...    # Jinja transforming the shown value
            font: 4                # device font id for the value overlay

    Layouts (``layout: auto`` picks by count):
      * ``list`` (3-5, and the auto default for 3-5): full-width rows —
        icon left, label on the top line, value below it; optional native
        header (clock by default) top-right.
      * ``grid`` (2-4): cells with the label on top, a large centered icon,
        and the value centered underneath.
      * 1-2 slots auto → big rows; 6-8 auto → compact icon+value grid.
    """
    slots: list[dict[str, Any]] = list(page.get("slots") or [])[:MAX_SLOTS]
    if len(slots) < 1:
        raise ValueError("sensor_grid card needs at least one slot")

    layout = str(page.get("layout", "auto")).lower()
    if layout == "auto":
        mode = "rows" if len(slots) <= 2 else "list" if len(slots) <= 5 else "compact"
    elif layout == "list":
        mode = "list" if len(slots) <= 5 else "compact"
    elif layout == "grid":
        mode = "rows" if len(slots) <= 2 else "quad" if len(slots) <= 4 else "compact"
    else:
        raise ValueError(f"sensor_grid: unknown layout {layout!r}")

    tpl_base = poll_base.replace("/dispdata/", "/dispdata_tpl/")
    img = Image.new("RGB", (SCREEN_SIZE, SCREEN_SIZE), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    items: list[dict[str, Any]] = []
    font_default = int(page.get("font", 4))
    update_default = int(page.get("update_time", 10))
    # Labels as device items (type 22): the device scrolls them automatically
    # when the text is wider than TextWidth — long names stay readable instead
    # of being truncated in the baked background.
    scroll_labels = bool(page.get("scroll_labels", True))
    label_font_id = int(page.get("label_font", 2))
    label_color = str(page.get("label_color", "#808080"))

    def label_item(i: int, text: str, x: int, y: int, w: int) -> None:
        items.append(
            {
                "TextId": MAX_SLOTS + 2 + i,
                "type": 22,
                "x": x,
                "y": y,
                "dir": 0,
                "font": label_font_id,
                "TextWidth": max(16, w),
                "Textheight": 14,
                "speed": int(page.get("label_speed", 60)),
                "align": 1,
                "color": label_color,
                "TextString": str(text)[:64],
            }
        )

    def value_item(slot: dict, i: int, x: int, y: int, w: int, color: str, align: int = 1) -> None:
        entity_id = slot["entity_id"]
        if tpl := slot.get("value_template"):
            key = hashlib.md5(str(tpl).encode()).hexdigest()[:12]
            register_value_template(hass, key, str(tpl))
            url = f"{tpl_base}/{key}"
        else:
            url = f"{poll_base}/{quote(entity_id)}"
        items.append(
            {
                "TextId": i + 1,
                "type": 23,
                "x": x,
                "y": y,
                "dir": 0,
                "font": int(slot.get("font", font_default)),
                "TextWidth": max(16, w),
                "Textheight": 16,
                "speed": 50,
                "align": align,
                "color": color,
                "update_time": int(slot.get("update_time", update_default)),
                "TextString": url,
            }
        )

    # Optional native header (device-rendered clock/date/weather) top-right.
    header = str(page.get("header", "time_short")).lower()
    top = 0
    if mode == "list" and header not in ("none", "false", ""):
        native_type = NATIVE_KIND_TYPES.get(header)
        if native_type is None:
            raise ValueError(f"sensor_grid: unknown header kind {header!r}")
        items.append(
            {
                "TextId": MAX_SLOTS + 1,
                "type": native_type,
                "x": 64,
                "y": 1,
                "dir": 0,
                "font": int(page.get("header_font", font_default)),
                "TextWidth": 62,
                "Textheight": 16,
                "speed": 50,
                "align": 5,  # right (Times Gate: 1 left / 3 centre / 5 right)
                "color": str(page.get("header_color", "#FFFFFF")),
            }
        )
        top = 15

    if mode == "list":
        row_h = (SCREEN_SIZE - top) // len(slots)
        for i, slot in enumerate(slots):
            entity_id = slot.get("entity_id")
            if not entity_id:
                raise ValueError(f"sensor_grid slot #{i} is missing entity_id")
            state = hass.states.get(entity_id)
            color = _resolve_color(hass, slot)
            icon = slot.get("icon") or icon_for_state(state)
            label = slot.get("name")
            if label is None:
                label = state.name if state is not None else entity_id.split(".")[-1]

            y = top + i * row_h
            icon_size = min(24, row_h - 4)
            draw_icon(draw, icon, (2, y + (row_h - icon_size) // 2), icon_size, color)
            text_x = 2 + icon_size + 5
            if scroll_labels:
                label_item(i, label, text_x, y + 1, SCREEN_SIZE - text_x - 2)
            else:
                draw.text((text_x, y + 1), str(label)[:18], font=_label_font(11), fill=_LABEL_COLOR)
            value_item(slot, i, text_x, y + 12, SCREEN_SIZE - text_x - 2, color)
            if i:
                draw.line([(0, y), (SCREEN_SIZE, y)], fill=(35, 35, 35))
    else:
        cells = _layout_cells(len(slots))
        for i, slot in enumerate(slots):
            x, y, w, h = cells[i]
            entity_id = slot.get("entity_id")
            if not entity_id:
                raise ValueError(f"sensor_grid slot #{i} is missing entity_id")
            state = hass.states.get(entity_id)
            color = _resolve_color(hass, slot)
            icon = slot.get("icon") or icon_for_state(state)
            label = slot.get("name")
            if label is None:
                label = state.name if state is not None else entity_id.split(".")[-1]

            if mode == "rows":
                icon_size = 32
                draw_icon(draw, icon, (6, y + (h - icon_size) // 2), icon_size, color)
                text_x = 6 + icon_size + 6
                if scroll_labels:
                    label_item(i, label, text_x, y + 10, SCREEN_SIZE - text_x - 2)
                else:
                    draw.text((text_x, y + 10), str(label)[:16], font=_label_font(11), fill=_LABEL_COLOR)
                value_item(slot, i, text_x, y + 26, SCREEN_SIZE - text_x - 2, color)
            elif mode == "quad":
                # Label on top (centered), large icon in the middle, value below.
                label_txt = str(label)[:11]
                lf = _label_font(10)
                lw = draw.textlength(label_txt, font=lf)
                draw.text((x + (w - lw) // 2, y + 2), label_txt, font=lf, fill=_LABEL_COLOR)
                icon_size = 26
                draw_icon(draw, icon, (x + (w - icon_size) // 2, y + 14), icon_size, color)
                value_item(slot, i, x + 2, y + h - 20, w - 4, color, align=3)
            else:  # compact
                icon_size = min(16, h - 4)
                draw_icon(draw, icon, (x + 3, y + (h - icon_size) // 2), icon_size, color)
                text_x = x + 3 + icon_size + 3
                value_item(slot, i, text_x, y + (h - 16) // 2, x + w - text_x - 2, color)

        # Separator lines between cells (subtle, dark gray).
        if len(slots) > 2:
            draw.line([(SCREEN_SIZE // 2, 0), (SCREEN_SIZE // 2, SCREEN_SIZE)], fill=(40, 40, 40))
        for _, cy, _, ch in cells[1::2]:
            if cy > 0:
                draw.line([(0, cy), (SCREEN_SIZE, cy)], fill=(40, 40, 40))

    buf = BytesIO()
    # The device treats PURE white (255,255,255) in BackgroudGif as
    # transparent (verified on-device 2026-07-05: white pixels simply vanish,
    # leaving antialiased edges as an "outline"). Clamp 255 -> 254 per
    # channel — visually identical, but the device keeps the pixels.
    img = Image.eval(img, lambda v: 254 if v == 255 else v)
    # The device fetches BackgroudGif as an actual GIF; static single frame.
    img.convert("P", palette=Image.Palette.ADAPTIVE).save(buf, "GIF")
    return buf.getvalue(), items


CARD_RENDERERS = {
    "sensor_grid": render_sensor_grid,
}
