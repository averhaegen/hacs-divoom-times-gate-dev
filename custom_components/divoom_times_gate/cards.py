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

import logging
from io import BytesIO
from typing import Any
from urllib.parse import quote

from PIL import Image, ImageDraw, ImageFont

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template

from .const import SCREEN_SIZE
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
        update_time: 10            # poll seconds, page-wide default
        slots:                     # 2-8 entries
          - entity_id: sensor.solar_power
            name: Solar            # label; defaults to the entity's name
            icon: mdi:solar-power  # defaults to entity icon / device_class
            color: "#FFB300"       # icon + value colour
            color_template: ...    # optional template overriding `color`
            font: 4                # device font id for the value overlay
    """
    slots: list[dict[str, Any]] = list(page.get("slots") or [])[:MAX_SLOTS]
    if len(slots) < 1:
        raise ValueError("sensor_grid card needs at least one slot")

    cells = _layout_cells(len(slots))
    # Cell anatomy per density:
    #   rows (2):    big icon left, label top-right, value under the label
    #   quad (3-4):  small icon + label on the top row, value across the cell
    #   compact (5+): small icon left, value right, no label (icon = label)
    mode = "rows" if len(slots) <= 2 else "quad" if len(slots) <= 4 else "compact"
    img = Image.new("RGB", (SCREEN_SIZE, SCREEN_SIZE), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    items: list[dict[str, Any]] = []

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
            icon_size = 28
            draw_icon(draw, icon, (x + 6, y + (h - icon_size) // 2), icon_size, color)
            text_x = x + 6 + icon_size + 6
            draw.text((text_x, y + 8), str(label)[:16], font=_label_font(10), fill=_LABEL_COLOR)
            value_rect = (text_x, y + 24, x + w - text_x - 2)
        elif mode == "quad":
            icon_size = 14
            draw_icon(draw, icon, (x + 4, y + 4), icon_size, color)
            draw.text((x + 4 + icon_size + 3, y + 6), str(label)[:9], font=_label_font(9), fill=_LABEL_COLOR)
            value_rect = (x + 4, y + h - 24, w - 8)
        else:  # compact
            icon_size = min(16, h - 4)
            draw_icon(draw, icon, (x + 3, y + (h - icon_size) // 2), icon_size, color)
            text_x = x + 3 + icon_size + 3
            value_rect = (text_x, y + (h - 16) // 2, x + w - text_x - 2)

        # Value zone: the device polls and draws this itself (type 23).
        value_x, value_y, value_w = value_rect
        items.append(
            {
                "TextId": i + 1,
                "type": 23,
                "x": value_x,
                "y": value_y,
                "dir": 0,
                "font": int(slot.get("font", page.get("font", 4))),
                "TextWidth": max(16, value_w),
                "Textheight": 16,
                "speed": 50,
                "align": 1,
                "color": color,
                "update_time": int(slot.get("update_time", page.get("update_time", 10))),
                "TextString": f"{poll_base}/{quote(entity_id)}",
            }
        )

    # Separator lines between cells (subtle, dark gray).
    if len(slots) > 2:
        draw.line([(SCREEN_SIZE // 2, 0), (SCREEN_SIZE // 2, SCREEN_SIZE)], fill=(40, 40, 40))
    for _, cy, _, ch in cells[1::2]:
        if cy > 0:
            draw.line([(0, cy), (SCREEN_SIZE, cy)], fill=(40, 40, 40))

    buf = BytesIO()
    # The device fetches BackgroudGif as an actual GIF; static single frame.
    img.convert("P", palette=Image.Palette.ADAPTIVE).save(buf, "GIF")
    return buf.getvalue(), items


CARD_RENDERERS = {
    "sensor_grid": render_sensor_grid,
}
