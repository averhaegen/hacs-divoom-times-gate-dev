"""Render a Times Gate screen from a Pixoo-compatible page config.

A screen is a "page" dict using the same schema as
gickowtf/pixoo-homeassistant, so configs are portable between the two devices:

    page_type: components        # components | clock | off
    enabled: "{{ ... }}"         # optional template; if false the screen is skipped
    variables: {name: "{{ ... }}"}
    components:
      - type: text       # content, position [x,y], color, font, align
      - type: image      # image_path | image_url | image_data, position, width/height
      - type: rectangle  # position [x,y], size [w,h], color, filled
      - type: templatable# template -> list of component dicts

It also implements upstream's three fixed-layout pages, which take templatable
fields instead of a component list: ``page_type: pv``, ``page_type:
progress_bar`` and ``page_type: fuel``. Their layouts are ported from
gickowtf/pixoo-homeassistant ``pages/solar.py``, ``pages/progress_bar.py`` and
``pages/fuel.py`` (MIT, (c) 2023 gickowtf). Upstream draws them straight onto
its Pixoo object; here they resolve to the same internal draw list the
``components`` path produces, so they share one drawing implementation.

Pixoo component pages are always rendered on a 64x64 canvas, then scaled to the
device's 128 with nearest-neighbour so copied Pixoo pages stay pixel-identical
(just doubled).
"""
from __future__ import annotations

import ast
import base64
from datetime import datetime
from io import BytesIO
import logging
import os
import re
from typing import Any
import urllib.request

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
from PIL import Image, ImageOps, ImageSequence

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
    """Render a components page to a 128x128 JPEG (always scaled from 64x64).

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
    page_type = str(page.get("page_type") or page.get("type") or "components").lower()
    special = _SPECIAL_PAGES.get(page_type)
    if special is not None:
        return {"components": special(hass, page)}

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

    return {"components": resolved_components}


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
            "position": tuple(component["position"]),
            "upper": True,
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
        for item in _render_templatable(hass, component, variables)[::-1]:
            components.insert(index + 1, item)
        return None

    return None


def _render_templatable(
    hass: HomeAssistant, component: dict[str, Any], variables: dict[str, Any]
) -> list[dict[str, Any]]:
    """Expand a ``templatable`` component into a list of component dicts.

    The template must render to a list of dicts. HA's ``async_render`` already
    parses a literal result into native Python; when it hands back a string
    (for example because the template used ``| tojson``) fall back to
    ``ast.literal_eval``, never ``eval``. Anything that is not a list of dicts
    is rejected with a log line rather than fed to the drawing code, where it
    would raise once per component on every tick.
    """
    rendered = Template(str(component.get("template", [])), hass).async_render(
        variables=variables
    )
    if isinstance(rendered, str):
        try:
            rendered = ast.literal_eval(rendered)
        except (ValueError, SyntaxError) as err:
            _LOGGER.error(
                "templatable component: template did not render to a Python "
                "literal (%s): %.120s",
                err,
                rendered,
            )
            return []
    if not isinstance(rendered, (list, tuple)):
        _LOGGER.error(
            "templatable component: expected a list of component dicts, got %s",
            type(rendered).__name__,
        )
        return []
    items = [item for item in rendered if isinstance(item, dict)]
    if len(items) != len(rendered):
        _LOGGER.error(
            "templatable component: ignored %d non-dict entries in the "
            "rendered list",
            len(rendered) - len(items),
        )
    return items


def _render_resolved_page(resolved: dict[str, Any]) -> bytes:
    """Draw a pre-resolved (template-free) page. Runs in the executor."""
    canvas = PixelCanvas(64)
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
        font_spec = component["font"] if isinstance(component["font"], str) else None
        font = font_by_name(font_spec)
        if component.get("upper", True):
            text = text.upper()
        canvas.draw_text(text, component["position"], color, font, align)

    elif ctype == "fill_rect":
        # Absolute top-left/bottom-right fill, as upstream's fixed-layout pages
        # call draw_filled_rectangle. Distinct from the `rectangle` component,
        # whose config takes a size and is off-by-one adjusted at resolve time.
        top_left, bottom_right = component["bounds"]
        canvas.draw_filled_rectangle(top_left, bottom_right, component["color"])

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


# --------------------------------------------------------------------------
# Fixed-layout pages ported from gickowtf/pixoo-homeassistant (MIT, (c) 2023
# gickowtf): pages/solar.py -> `pv`, pages/progress_bar.py -> `progress_bar`,
# pages/fuel.py -> `fuel`. Upstream draws these straight onto its Pixoo
# object. Here each one resolves to the same internal draw list the
# `components` path builds, so there is one drawing implementation and the
# 64x64 canvas is upscaled to 128 the same way. Coordinates, colours and font
# choices are kept identical to upstream so a copied page looks the same.
# --------------------------------------------------------------------------

_GREY = (51, 51, 51)
_LIGHT_GREY = (151, 151, 151)
_WHITE = (255, 255, 255)
_BLACK = (0, 0, 0)
_RED = (255, 0, 68)
_BLUE = (0, 123, 255)
_GREEN = (4, 204, 2)
_YELLOW = (255, 230, 0)
_DARK_GREY = (36, 36, 36)
_PV_GREY = (131, 131, 131)
_PV_YELLOW = (255, 175, 0)


def _fill(bounds, color) -> dict[str, Any]:
    return {"type": "fill_rect", "bounds": bounds, "color": color}


def _text(content, position, color, font) -> dict[str, Any]:
    """A draw op for a fixed-layout page. Never uppercased: upstream's pages
    pass their strings through verbatim, and five_pix/pico_8 have lowercase
    glyphs, so forcing upper would change the pixels."""
    return {
        "type": "text",
        "content": str(content),
        "color": color,
        "align": "",
        "font": font,
        "position": tuple(position),
        "upper": False,
    }


def _asset(name: str, position) -> dict[str, Any]:
    return {
        "type": "image",
        "source": {"image_asset": name},
        "resample_mode": "box",
        "width": None,
        "height": None,
        "position": tuple(position),
    }


def _required_tpl(hass: HomeAssistant, page: dict[str, Any], key: str) -> str:
    """Render a required templatable field, or raise with the field name.

    Upstream aborts the page (leaving the panel on its previous content) when a
    field is missing or its template fails. Raising here does the same: the
    coordinator logs it and skips the screen for this tick.
    """
    if key not in page:
        raise ValueError(f"page is missing required field '{key}'")
    return str(Template(str(page[key]), hass).async_render())


def _offset(page: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(page.get(key, default))
    except (TypeError, ValueError):
        return default


def _resolve_progress_bar(
    hass: HomeAssistant, page: dict[str, Any]
) -> list[dict[str, Any]]:
    """`page_type: progress_bar` (upstream pages/progress_bar.py)."""
    header = _required_tpl(hass, page, "header")
    footer = _required_tpl(hass, page, "footer")
    raw_progress = _required_tpl(hass, page, "progress")
    try:
        progress = int(float(raw_progress))
    except ValueError as err:
        raise ValueError(
            f"progress_bar: 'progress' is not a number ({raw_progress!r})"
        ) from err
    # The clock font only carries digits and a colon, so anything else in
    # time_end would render as "?". Upstream strips it; keep that.
    time_end = re.sub(
        r"[^0-9:]", "", str(Template(str(page.get("time_end", "")), hass).async_render())
    )

    bg_color = render_color(page.get("bg_color"), hass, _BLUE)
    header_font_color = render_color(page.get("header_font_color"), hass, _WHITE)
    progress_bar_color = render_color(page.get("progress_bar_color"), hass, _RED)
    progress_text_color = render_color(page.get("progress_text_color"), hass, _WHITE)
    time_color = render_color(page.get("time_color"), hass, _GREY)
    time_end_color = render_color(page.get("time_end_color"), hass, _LIGHT_GREY)
    footer_font_color = render_color(page.get("footer_font_color"), hass, _WHITE)

    header_offset = _offset(page, "header_offset", 2)
    footer_offset = _offset(page, "footer_offset", 2)
    percent_size = int(60 / 100 * progress)

    return [
        _fill(((0, 0), (63, 63)), bg_color),
        _fill(((0, 0), (63, 6)), _GREY),
        _text(header, (header_offset, 1), header_font_color, "five_pix"),
        _fill(((2, 25), (61, 33)), _GREY),
        _fill(((3, 26), (percent_size, 32)), progress_bar_color),
        _text(f"{progress} %", (4, 27), progress_text_color, "pico_8"),
        _text(datetime.now().strftime("%H:%M"), (15, 10), time_color, "clock"),
        _text(time_end, (15, 37), time_end_color, "clock"),
        _fill(((0, 57), (63, 63)), _GREY),
        _text(footer, (footer_offset, 58), footer_font_color, "five_pix"),
    ]


def _resolve_fuel(hass: HomeAssistant, page: dict[str, Any]) -> list[dict[str, Any]]:
    """`page_type: fuel` (upstream pages/fuel.py)."""
    values = {
        key: _required_tpl(hass, page, key)
        for key in (
            "title", "name1", "price1", "name2", "price2", "name3", "price3", "status",
        )
    }

    font_color = render_color(page.get("font_color"), hass, _WHITE)
    bg_color = render_color(page.get("bg_color"), hass, _YELLOW)
    price_color = render_color(page.get("price_color"), hass, _WHITE)
    title_color = render_color(page.get("title_color"), hass, _BLACK)
    stripe_color = render_color(page.get("stripe_color"), hass, font_color)
    title_offset = _offset(page, "title_offset", 2)

    now = datetime.now()
    ops = [
        _fill(((0, 57), (64, 64)), _DARK_GREY),
        _text(values["status"], (1, 58), font_color, "five_pix"),
        _fill(((0, 24), (64, 56)), bg_color),
    ]
    for row, (top, text_y) in enumerate(((26, 28), (36, 38), (46, 48)), start=1):
        ops += [
            _fill(((0, top), (61, top + 7)), _DARK_GREY),
            _text(values[f"name{row}"], (1, text_y), font_color, "five_pix"),
        ]
    # Redraw the right half so a long name is clipped where the price starts.
    ops += [
        _fill(((31, 24), (64, 56)), bg_color),
        _fill(((0, 56), (64, 56)), stripe_color),
    ]
    for row, (top, text_y) in enumerate(((26, 27), (36, 37), (46, 47)), start=1):
        ops += [
            _fill(((31, top), (61, top + 7)), _DARK_GREY),
            _text(values[f"price{row}"], (33, text_y), price_color, "gicko"),
        ]
    ops += [
        _fill(((0, 0), (63, 19)), bg_color),
        # eleven_pix has no lowercase glyphs, hence upstream's explicit upper().
        _text(values["title"].upper(), (title_offset, 2), title_color, "eleven_pix"),
        _fill(((0, 15), (64, 15)), stripe_color),
        _fill(((0, 16), (64, 22)), _DARK_GREY),
        _fill(((0, 23), (64, 23)), stripe_color),
        _text(now.strftime("%a"), (1, 17), font_color, "five_pix"),
        _text(now.strftime("%H:%M"), (22, 17), bg_color, "pico_8"),
        _text(now.strftime("%d-%m"), (45, 17), font_color, "pico_8"),
    ]
    return ops


# Battery icon by remaining capacity, highest matching band wins.
_PV_BATTERY_BANDS = (
    ("akku80-100.png", 80),
    ("akku60-80.png", 60),
    ("akku40-60.png", 40),
    ("akku20-40.png", 20),
    ("akku00-20.png", 0),
)


def _resolve_pv(hass: HomeAssistant, page: dict[str, Any]) -> list[dict[str, Any]]:
    """`page_type: pv` (upstream pages/solar.py).

    Icon and colour choices are hardcoded upstream (they key off the power and
    battery values), so there is nothing extra to configure here either.
    """
    numbers: dict[str, float] = {}
    for key in ("power", "storage", "discharge", "powerhousetotal", "vomNetz"):
        raw = _required_tpl(hass, page, key)
        try:
            numbers[key] = float(raw)
        except ValueError as err:
            raise ValueError(f"pv: '{key}' is not a number ({raw!r})") from err
    time_text = _required_tpl(hass, page, "time")

    power = numbers["power"]
    storage = numbers["storage"]
    discharge = numbers["discharge"]

    ops = [
        _text(time_text, (44, 1), _WHITE, "pico_8"),
        _asset("sunpower.png", (2, 1)),
        _text(power, (17, 8), _PV_YELLOW if power >= 1 else _PV_GREY, "gicko"),
        _text(discharge, (17, 18), _RED if discharge <= 0 else _GREEN, "gicko"),
    ]
    for name, threshold in _PV_BATTERY_BANDS:
        if storage >= threshold:
            ops.append(_asset(name, (2, 17)))
            break
    ops += [
        _text(f"{storage}%", (17, 25), _WHITE, "pico_8"),
        _asset("haus.png", (2, 33)),
        _text(numbers["powerhousetotal"], (17, 40), _BLUE, "gicko"),
        _asset("industry.png", (2, 49)),
        _text(numbers["vomNetz"], (17, 56), _PV_GREY, "gicko"),
    ]
    return ops


_SPECIAL_PAGES = {
    "pv": _resolve_pv,
    "progress_bar": _resolve_progress_bar,
    "fuel": _resolve_fuel,
}
