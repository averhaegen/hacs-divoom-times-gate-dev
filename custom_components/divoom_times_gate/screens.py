"""Render a Times Gate screen from a Pixoo-compatible page config.

A screen is a "page" dict using the same schema as
gickowtf/pixoo-homeassistant, so configs are portable between the two devices:

    page_type: components        # components | clock | off
    size: 64                     # canvas size; 64 (Pixoo-native, default) or 128
    enabled: "{{ ... }}"         # optional template; if false the screen is skipped
    variables: {name: "{{ ... }}"}
    components:
      - type: text       # content, position [x,y], color, font, align
      - type: image      # image_path | image_url | image_data, position, width/height
      - type: rectangle  # position [x,y], size [w,h], color, filled
      - type: templatable# template -> list of component dicts

Pixoo pages are designed for 64x64; we render at ``size`` then scale to the
device's 128 with nearest-neighbour, so a copied Pixoo page looks identical
(just pixel-doubled). Set ``size: 128`` for native-resolution screens.
"""
from __future__ import annotations

import base64
import logging
import urllib.request
from io import BytesIO
from typing import Any

from PIL import Image

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template

from .canvas import PixelCanvas, font_by_name
from .const import SCREEN_SIZE
from .vendor_pixoo._colors import render_color

_LOGGER = logging.getLogger(__name__)

_RESAMPLE = {
    "nearest": Image.NEAREST, "pixel_art": Image.NEAREST, "box": Image.BOX,
    "bilinear": Image.BILINEAR, "hamming": Image.HAMMING, "bicubic": Image.BICUBIC,
    "lanczos": Image.LANCZOS, "antialias": Image.LANCZOS,
}


def _tpl(hass: HomeAssistant, value: Any, variables: dict[str, Any]) -> str:
    return str(Template(str(value), hass).async_render(variables=variables))


def is_enabled(hass: HomeAssistant, page: dict[str, Any]) -> bool:
    try:
        rendered = _tpl(hass, page.get("enabled", "true"), {}).lower()
        return rendered in ("true", "yes", "1", "on")
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("Error rendering 'enabled' for screen: %s", err)
        return False


def render_black() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (SCREEN_SIZE, SCREEN_SIZE), (0, 0, 0)).save(buf, "JPEG", quality=95)
    return buf.getvalue()


def render_page(hass: HomeAssistant, page: dict[str, Any]) -> bytes:
    """Render a components page to a 128x128 JPEG (scaled from its canvas size)."""
    size = int(page.get("size", 64))
    canvas = PixelCanvas(size)

    variables: dict[str, Any] = {}
    for name, expr in (page.get("variables") or {}).items():
        try:
            variables[name] = Template(str(expr), hass).async_render()
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Variable %s template error: %s", name, err)
            variables[name] = ""

    components: list[dict[str, Any]] = list(page.get("components", []))
    index = 0
    while index < len(components):
        component = components[index]
        try:
            _draw_component(hass, canvas, component, variables, components, index)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Error drawing component %s: %s", component.get("type"), err)
        index += 1

    image = canvas.to_image(SCREEN_SIZE)
    buf = BytesIO()
    image.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def _draw_component(
    hass: HomeAssistant,
    canvas: PixelCanvas,
    component: dict[str, Any],
    variables: dict[str, Any],
    components: list[dict[str, Any]],
    index: int,
) -> None:
    ctype = component.get("type")

    if ctype == "text":
        text = _tpl(hass, component.get("content", ""), variables)
        font = font_by_name(component.get("font"))
        color = render_color(component.get("color"), hass, variables=variables)
        align = component.get("align", "").lower()
        # Pixoo uppercases all text; match it for visual parity.
        canvas.draw_text(text.upper(), tuple(component["position"]), color, font, align)

    elif ctype == "image":
        img = _load_image(hass, component, variables)
        if img is None:
            return
        resample = _RESAMPLE.get(
            _tpl(hass, component.get("resample_mode", "box"), variables).lower(), Image.BOX
        )
        width, height = component.get("width"), component.get("height")
        if width and height:
            img = img.resize((int(width), int(height)), resample)
        elif width or height:
            img.thumbnail((int(width or 100), int(height or 100)), resample)
        canvas.draw_image(img, tuple(component["position"]))

    elif ctype == "rectangle":
        color = render_color(component.get("color"), hass, variables=variables)
        pos = [int(_tpl(hass, p, variables)) for p in component["position"]]
        size = [int(_tpl(hass, s, variables)) for s in component["size"]]
        size = (size[0] - 1, size[1] - 1)
        filled = str(_tpl(hass, component.get("filled", True), variables)).lower() in (
            "true", "yes", "1", "on",
        )
        if filled:
            canvas.draw_filled_rectangle(pos, (pos[0] + size[0], pos[1] + size[1]), color)
        else:
            canvas.draw_line(pos, (pos[0] + size[0], pos[1]), color)
            canvas.draw_line((pos[0] + size[0], pos[1]), (pos[0] + size[0], pos[1] + size[1]), color)
            canvas.draw_line((pos[0] + size[0], pos[1] + size[1]), (pos[0], pos[1] + size[1]), color)
            canvas.draw_line((pos[0], pos[1] + size[1]), pos, color)

    elif ctype == "templatable":
        rendered = list(
            Template(str(component.get("template", [])), hass).async_render(variables=variables)
        )
        for item in rendered[::-1]:
            components.insert(index + 1, item)


def _load_image(hass, component, variables) -> Image.Image | None:
    if "image_path" in component:
        return Image.open(_tpl(hass, component["image_path"], variables))
    if "image_url" in component:
        url = _tpl(hass, component["image_url"], variables)
        with urllib.request.urlopen(url, timeout=9) as resp:  # noqa: S310 - user-configured URL
            return Image.open(BytesIO(resp.read()))
    if "image_data" in component:
        data = _tpl(hass, component["image_data"], variables)
        return Image.open(BytesIO(base64.b64decode(data)))
    return None
