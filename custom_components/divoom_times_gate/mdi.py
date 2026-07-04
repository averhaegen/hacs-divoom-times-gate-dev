"""Material Design Icons rendering for card backgrounds.

Bundles the MDI webfont (mdi_assets/, Apache-2.0 — see LICENSE there) plus a
name→codepoint map generated from the @mdi/font CSS, so cards can draw any
`mdi:*` icon with Pillow at arbitrary size/color.

Icon resolution order for an entity: explicit `icon` attribute on the state →
device_class fallback table → generic default. HA's own per-domain default
icons live in the frontend, so the backend can't read them — the fallback
table below covers the common sensor device classes instead.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from PIL import ImageDraw, ImageFont

from homeassistant.core import State

_LOGGER = logging.getLogger(__name__)

_ASSETS = Path(__file__).parent / "mdi_assets"
_FONT_PATH = _ASSETS / "materialdesignicons-webfont.ttf"
_CODEPOINTS_PATH = _ASSETS / "codepoints.json"

DEFAULT_ICON = "mdi:eye"

# Common device_class → icon fallbacks (subset; extend as cards need them).
DEVICE_CLASS_ICONS: dict[str, str] = {
    "battery": "mdi:battery",
    "carbon_dioxide": "mdi:molecule-co2",
    "current": "mdi:current-ac",
    "date": "mdi:calendar",
    "distance": "mdi:map-marker-distance",
    "door": "mdi:door",
    "energy": "mdi:lightning-bolt",
    "gas": "mdi:meter-gas",
    "humidity": "mdi:water-percent",
    "illuminance": "mdi:brightness-5",
    "lock": "mdi:lock",
    "moisture": "mdi:water-alert",
    "motion": "mdi:motion-sensor",
    "power": "mdi:flash",
    "power_factor": "mdi:angle-acute",
    "pressure": "mdi:gauge",
    "signal_strength": "mdi:wifi",
    "speed": "mdi:speedometer",
    "temperature": "mdi:thermometer",
    "timestamp": "mdi:clock-outline",
    "voltage": "mdi:sine-wave",
    "volume": "mdi:car-coolant-level",
    "water": "mdi:water",
    "weight": "mdi:weight",
    "window": "mdi:window-closed",
}


@lru_cache(maxsize=1)
def _codepoints() -> dict[str, int]:
    try:
        return json.loads(_CODEPOINTS_PATH.read_text())
    except (OSError, ValueError) as err:
        _LOGGER.error("MDI codepoints map failed to load: %s", err)
        return {}


@lru_cache(maxsize=8)
def _font(size: int) -> ImageFont.FreeTypeFont | None:
    try:
        return ImageFont.truetype(str(_FONT_PATH), size)
    except OSError as err:
        _LOGGER.error("MDI font failed to load: %s", err)
        return None


def icon_char(name: str) -> str | None:
    """Return the font character for an ``mdi:name`` / ``name`` icon."""
    codepoint = _codepoints().get(name.removeprefix("mdi:"))
    return chr(codepoint) if codepoint else None


def _battery_icon(state: State) -> str:
    """State-dependent battery icon, mirroring HA's frontend battery logic:
    round the level to the nearest 10 → ``mdi:battery-10`` … ``mdi:battery-90``,
    full → ``mdi:battery``, near-empty → ``mdi:battery-outline``, non-numeric →
    ``mdi:battery-unknown``. (Charging variants need a second entity; a card
    could add that later via an explicit ``icon`` template.)
    """
    try:
        level = float(state.state)
    except (TypeError, ValueError):
        return "mdi:battery-unknown"
    decile = round(level / 10) * 10
    if decile >= 100:
        return "mdi:battery"
    if decile <= 0:
        return "mdi:battery-outline"
    return f"mdi:battery-{decile}"


# device_class → state-dependent icon resolver (frontend-style dynamic icons).
_DYNAMIC_ICONS = {
    "battery": _battery_icon,
}


def icon_for_state(state: State | None) -> str:
    """Best icon name for an entity state (see module docstring for order).

    An explicit ``icon`` attribute always wins; otherwise device classes with
    a dynamic resolver (battery fill level) get a state-dependent icon, then
    the static device_class table, then the generic default.
    """
    if state is None:
        return DEFAULT_ICON
    if icon := state.attributes.get("icon"):
        return icon
    if device_class := state.attributes.get("device_class"):
        if dynamic := _DYNAMIC_ICONS.get(device_class):
            return dynamic(state)
        if icon := DEVICE_CLASS_ICONS.get(device_class):
            return icon
    return DEFAULT_ICON


def draw_icon(
    draw: ImageDraw.ImageDraw,
    icon: str,
    xy: tuple[int, int],
    size: int,
    color: str | tuple[int, int, int],
) -> bool:
    """Draw an mdi icon with its top-left at ``xy``. Returns False if unknown."""
    char = icon_char(icon)
    font = _font(size)
    if char is None or font is None:
        if char is None:
            _LOGGER.warning("Unknown MDI icon %r", icon)
        return False
    # The glyphs sit on a text baseline; anchor via textbbox so the visible
    # glyph (not the em-box) lands at xy.
    bbox = draw.textbbox((0, 0), char, font=font)
    draw.text((xy[0] - bbox[0], xy[1] - bbox[1]), char, font=font, fill=color)
    return True
