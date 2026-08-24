"""Convert between a screen's page configuration and a form's fields.

The forms in the options flow do not own the configuration. They read a page
dict, show a few fields, and write the same page dict back. Everything a form
cannot express stays reachable through the YAML editor, and a page that carries
such a thing is never offered a form at all.

That last rule is the whole point of this module. A form that quietly drops the
per-slot ``value_template`` somebody spent an evening on is worse than no form.
``unsupported_reason`` decides, in one place, whether a page is safe to edit
through a form, and says why when it is not.
"""
from __future__ import annotations

from typing import Any

from .cards import MAX_SLOTS, THEMES
from .const import DEFAULT_DURATION

KIND_SENSORS = "sensors"
KIND_FACE = "face"
KIND_OFF = "off"

CONF_ENTITIES = "entities"
CONF_THEME = "theme"
CONF_DURATION = "duration"
CONF_CLOCK_ID = "clock_id"

# Keys a form writes, per page type. Anything else on the page means the form
# would drop it, so the page is YAML-only.
_SENSOR_KEYS = {"page_type", "card", "name", "theme", "slots", "duration"}
_SENSOR_SLOT_KEYS = {"entity_id", "name"}
_FACE_KEYS = {"page_type", "clock_id", "id", "duration"}
_OFF_KEYS = {"page_type", "duration"}


def single_page(pages: Any) -> dict[str, Any] | None:
    """The one page on a screen, or ``None`` when there is not exactly one."""
    if isinstance(pages, dict):
        return pages
    if isinstance(pages, list) and len(pages) == 1 and isinstance(pages[0], dict):
        return pages[0]
    return None


def page_kind(pages: Any) -> str | None:
    """Which form fits this screen, or ``None`` when none does."""
    page = single_page(pages)
    if page is None:
        return None
    page_type = str(page.get("page_type") or page.get("type") or "components").lower()
    if page_type == "off":
        return KIND_OFF
    if page_type == "clock":
        return KIND_FACE
    if page_type == "card" and str(page.get("card") or "") == "sensor_grid":
        return KIND_SENSORS
    return None


def unsupported_reason(pages: Any) -> str | None:
    """Why this screen may only be edited as YAML, or ``None`` when a form fits.

    The sentence is shown to the user, so it names the thing that would be
    lost rather than the rule that fired.
    """
    if isinstance(pages, list) and len(pages) > 1:
        return "it rotates through several pages"
    page = single_page(pages)
    if page is None:
        return "it is not a single page"
    kind = page_kind(pages)
    if kind is None:
        page_type = str(page.get("page_type") or page.get("type") or "components")
        if page_type == "card":
            return f"it is a {page.get('card') or 'custom'} card"
        return f"it is a {page_type} page"
    allowed = {
        KIND_SENSORS: _SENSOR_KEYS,
        KIND_FACE: _FACE_KEYS,
        KIND_OFF: _OFF_KEYS,
    }[kind]
    if extra := sorted(set(page) - allowed):
        return f"it sets {', '.join(extra)}, which the form cannot show"
    if kind == KIND_SENSORS:
        for slot in page.get("slots") or []:
            if not isinstance(slot, dict):
                return "one of its slots is not a mapping"
            if slot_extra := sorted(set(slot) - _SENSOR_SLOT_KEYS):
                return (
                    f"one of its sensors sets {', '.join(slot_extra)}, "
                    "which the form cannot show"
                )
        if len(page.get("slots") or []) > MAX_SLOTS:
            return f"it holds more than {MAX_SLOTS} sensors"
    return None


def duration_of(pages: Any, default: int = DEFAULT_DURATION) -> int:
    """The page's rotation duration, falling back to the shipped default."""
    page = single_page(pages) or {}
    try:
        return int(page.get("duration", default))
    except (TypeError, ValueError):
        return default


# --- sensors ---------------------------------------------------------------


def sensor_defaults(pages: Any) -> dict[str, Any]:
    """Form defaults for a sensor screen, empty when there is nothing to read."""
    page = single_page(pages) or {}
    slots = page.get("slots") or [] if page_kind(pages) == KIND_SENSORS else []
    return {
        CONF_ENTITIES: [
            str(slot["entity_id"])
            for slot in slots
            if isinstance(slot, dict) and slot.get("entity_id")
        ],
        CONF_THEME: str(page.get("theme") or "dark"),
        CONF_DURATION: duration_of(pages),
    }


def sensor_page(user_input: dict[str, Any]) -> dict[str, Any]:
    """Turn the sensor form's fields into a ``sensor_grid`` card page."""
    entities = [str(e) for e in user_input.get(CONF_ENTITIES) or []][:MAX_SLOTS]
    theme = str(user_input.get(CONF_THEME) or "dark")
    return {
        "page_type": "card",
        "card": "sensor_grid",
        "theme": theme if theme in THEMES else "dark",
        "duration": int(user_input.get(CONF_DURATION, DEFAULT_DURATION)),
        "slots": [{"entity_id": entity} for entity in entities],
    }


# --- native face and off ---------------------------------------------------


def face_defaults(pages: Any) -> dict[str, Any]:
    """Form defaults for a native face screen."""
    page = single_page(pages) or {}
    clock_id = page.get("clock_id", page.get("id", 0))
    try:
        current = int(clock_id)
    except (TypeError, ValueError):
        current = 0
    return {CONF_CLOCK_ID: str(current), CONF_DURATION: duration_of(pages)}


def face_page(user_input: dict[str, Any]) -> dict[str, Any]:
    """Turn the face form's fields into a ``clock`` page."""
    return {
        "page_type": "clock",
        "clock_id": int(user_input[CONF_CLOCK_ID]),
        "duration": int(user_input.get(CONF_DURATION, DEFAULT_DURATION)),
    }


def off_page() -> dict[str, Any]:
    """A black screen."""
    return {"page_type": "off"}
