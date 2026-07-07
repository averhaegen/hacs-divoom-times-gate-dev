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
import os
import urllib.request
from io import BytesIO
from typing import Any

from PIL import Image, ImageOps, ImageSequence

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template

from .canvas import PixelCanvas, font_by_name, is_scalable_font
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


def normalize_pages(screen_cfg: Any) -> list[dict[str, Any]]:
    """A screen config is a list of pages; a bare dict is a single static page."""
    if isinstance(screen_cfg, dict):
        return [screen_cfg]
    if isinstance(screen_cfg, list):
        return [p for p in screen_cfg if isinstance(p, dict)]
    return []


def page_duration(page: dict[str, Any], default: int) -> int:
    try:
        return max(1, int(page.get("duration", default)))
    except (TypeError, ValueError):
        return default


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


_IMAGE_MAX_FRAMES = 40  # device limit for SendHttpGif animations (docs/API.md §5)


async def render_image_frames(
    hass: HomeAssistant, page: dict[str, Any]
) -> tuple[list[bytes], int]:
    """Render an ``image`` page (photo or animated GIF) to 128x128 JPEG frames.

    Returns ``(frames, speed_ms)``. Sources (same keys as image components):
    ``image_path``, ``image_url``, ``image_asset``, ``image_data``.
    ``fit: cover`` (default) center-crops to fill the square; ``fit: contain``
    letterboxes on black. Animated GIFs are capped at 40 frames (device
    limit); ``speed`` overrides the GIF's own frame duration (ms).

    Templates in the source fields are rendered here, on the event loop
    (``Template.async_render`` isn't thread-safe); the actual image
    fetch/decode/resize is dispatched to the executor.
    """
    resolved_source = _resolve_image_source(hass, page, {})
    if resolved_source is None:
        raise ValueError(
            "image page needs one of image_path / image_url / image_asset / image_data"
        )
    return await hass.async_add_executor_job(
        _render_image_frames_sync, resolved_source, page
    )


def _render_image_frames_sync(
    resolved_source: dict[str, str], page: dict[str, Any]
) -> tuple[list[bytes], int]:
    img = _load_image_resolved(resolved_source)
    if img is None:
        raise ValueError(
            "image page needs one of image_path / image_url / image_asset / image_data"
        )

    fit = str(page.get("fit", "cover")).lower()

    def _fit_frame(frame: Image.Image) -> Image.Image:
        frame = frame.convert("RGB")
        if fit == "contain":
            frame.thumbnail((SCREEN_SIZE, SCREEN_SIZE))
            out = Image.new("RGB", (SCREEN_SIZE, SCREEN_SIZE), (0, 0, 0))
            out.paste(
                frame,
                ((SCREEN_SIZE - frame.width) // 2, (SCREEN_SIZE - frame.height) // 2),
            )
            return out
        return ImageOps.fit(frame, (SCREEN_SIZE, SCREEN_SIZE))

    frames: list[bytes] = []
    durations: list[int] = []
    for raw in ImageSequence.Iterator(img):
        buf = BytesIO()
        _fit_frame(raw).save(buf, "JPEG", quality=95)
        frames.append(buf.getvalue())
        durations.append(int(raw.info.get("duration", 200)))
        if len(frames) >= _IMAGE_MAX_FRAMES:
            _LOGGER.warning(
                "image page: animation truncated to %d frames (device limit)",
                _IMAGE_MAX_FRAMES,
            )
            break

    speed = int(page.get("speed", max(50, sum(durations) // len(durations))))
    return frames, speed


async def render_page(hass: HomeAssistant, page: dict[str, Any]) -> bytes:
    """Render a components page to a 128x128 JPEG (scaled from its canvas size).

    Templates (``variables``, per-component ``content``/``color``/position/
    ``templatable`` expansion/image source) are all rendered here, on the
    event loop — ``Template.async_render`` requires the loop thread. Only the
    actual PIL drawing (the ``_render_resolved_page`` call) runs in the
    executor.
    """
    resolved = _resolve_page(hass, page)
    return await hass.async_add_executor_job(_render_resolved_page, resolved)


def _resolve_page(hass: HomeAssistant, page: dict[str, Any]) -> dict[str, Any]:
    """Render every template in ``page`` into plain literal values.

    Must run on the event loop. Returns a page-shaped dict whose components
    carry only resolved values, safe to draw from a worker thread.
    """
    variables: dict[str, Any] = {}
    for name, expr in (page.get("variables") or {}).items():
        try:
            variables[name] = Template(str(expr), hass).async_render()
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Variable %s template error: %s", name, err)
            variables[name] = ""

    components: list[dict[str, Any]] = list(page.get("components", []))
    resolved_components: list[dict[str, Any]] = []
    index = 0
    while index < len(components):
        component = components[index]
        try:
            resolved = _resolve_component(hass, component, variables, components, index)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Error resolving component %s: %s", component.get("type"), err)
            resolved = None
        if resolved is not None:
            resolved_components.append(resolved)
        index += 1

    return {"size": int(page.get("size", 64)), "components": resolved_components}


def _resolve_component(
    hass: HomeAssistant,
    component: dict[str, Any],
    variables: dict[str, Any],
    components: list[dict[str, Any]],
    index: int,
) -> dict[str, Any] | None:
    """Render one component's templated fields into literals (event loop)."""
    ctype = component.get("type")

    if ctype == "text":
        return {
            "type": "text",
            "content": _tpl(hass, component.get("content", ""), variables),
            "color": render_color(component.get("color"), hass, variables=variables),
            "align": component.get("align", "").lower(),
            "font": component.get("font"),
            "max_width": component.get("max_width"),
            "position": tuple(component["position"]),
        }

    if ctype == "image":
        source = _resolve_image_source(hass, component, variables)
        if source is None:
            return None
        return {
            "type": "image",
            "source": source,
            "resample_mode": _tpl(
                hass, component.get("resample_mode", "box"), variables
            ).lower(),
            "width": component.get("width"),
            "height": component.get("height"),
            "position": tuple(component["position"]),
        }

    if ctype == "rectangle":
        pos = [int(_tpl(hass, p, variables)) for p in component["position"]]
        size = [int(_tpl(hass, s, variables)) for s in component["size"]]
        filled = str(_tpl(hass, component.get("filled", True), variables)).lower() in (
            "true", "yes", "1", "on",
        )
        return {
            "type": "rectangle",
            "color": render_color(component.get("color"), hass, variables=variables),
            "position": pos,
            "size": (size[0] - 1, size[1] - 1),
            "filled": filled,
        }

    if ctype == "templatable":
        rendered = list(
            Template(str(component.get("template", [])), hass).async_render(variables=variables)
        )
        for item in rendered[::-1]:
            components.insert(index + 1, item)
        return None

    return None


def _render_resolved_page(resolved: dict[str, Any]) -> bytes:
    """Draw a pre-resolved (template-free) page. Runs in the executor."""
    canvas = PixelCanvas(resolved["size"])
    for component in resolved["components"]:
        try:
            _draw_component(canvas, component)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Error drawing component %s: %s", component.get("type"), err)

    image = canvas.to_image(SCREEN_SIZE)
    buf = BytesIO()
    image.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def _draw_component(canvas: PixelCanvas, component: dict[str, Any]) -> None:
    """Draw one already-resolved component (no templates left to render)."""
    ctype = component["type"]

    if ctype == "text":
        text = component["content"]
        color = component["color"]
        align = component["align"]
        font_spec = component["font"]
        if is_scalable_font(font_spec):
            # Native scalable TrueType: keep original case, auto-fit to width.
            max_width = component["max_width"]
            canvas.draw_text_scalable(
                text, component["position"], color, int(font_spec), align,
                int(max_width) if max_width else None,
            )
        else:
            # Bitmap font: Pixoo uppercases all text — match for visual parity.
            font = font_by_name(font_spec)
            canvas.draw_text(text.upper(), component["position"], color, font, align)

    elif ctype == "image":
        img = _load_image_resolved(component["source"])
        if img is None:
            return
        resample = _RESAMPLE.get(component["resample_mode"], Image.BOX)
        width, height = component["width"], component["height"]
        if width and height:
            img = img.resize((int(width), int(height)), resample)
        elif width or height:
            img.thumbnail((int(width or 100), int(height or 100)), resample)
        canvas.draw_image(img, component["position"])

    elif ctype == "rectangle":
        color = component["color"]
        pos = component["position"]
        size = component["size"]
        if component["filled"]:
            canvas.draw_filled_rectangle(pos, (pos[0] + size[0], pos[1] + size[1]), color)
        else:
            canvas.draw_line(pos, (pos[0] + size[0], pos[1]), color)
            canvas.draw_line((pos[0] + size[0], pos[1]), (pos[0] + size[0], pos[1] + size[1]), color)
            canvas.draw_line((pos[0] + size[0], pos[1] + size[1]), (pos[0], pos[1] + size[1]), color)
            canvas.draw_line((pos[0], pos[1] + size[1]), pos, color)


def _resolve_image_source(hass, component, variables) -> dict[str, str] | None:
    """Render an image component/page's source field(s) into a literal dict.

    Runs on the event loop (templates only, no I/O). The returned dict has a
    single key naming which source was used, for ``_load_image_resolved``.
    """
    if "image_asset" in component:
        # A bundled icon, e.g. image_asset: sunpower.png (see img/). Assets are
        # flat filenames; basename() blocks `../` escaping the img/ directory.
        name = os.path.basename(_tpl(hass, component["image_asset"], variables))
        return {"image_asset": name}
    if "image_path" in component:
        return {"image_path": _tpl(hass, component["image_path"], variables)}
    if "image_url" in component:
        return {"image_url": _tpl(hass, component["image_url"], variables)}
    if "image_data" in component:
        return {"image_data": _tpl(hass, component["image_data"], variables)}
    return None


def _load_image_resolved(source: dict[str, str]) -> Image.Image | None:
    """Open an image from an already-resolved (template-free) source dict.

    Blocking I/O (disk/network) — must run in the executor.
    """
    if "image_asset" in source:
        return Image.open(os.path.join(os.path.dirname(__file__), "img", source["image_asset"]))
    if "image_path" in source:
        return Image.open(source["image_path"])
    if "image_url" in source:
        with urllib.request.urlopen(  # noqa: S310 - user-configured URL
            source["image_url"], timeout=9
        ) as resp:
            return Image.open(BytesIO(resp.read()))
    if "image_data" in source:
        return Image.open(BytesIO(base64.b64decode(source["image_data"])))
    return None
