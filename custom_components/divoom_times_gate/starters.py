"""Starters: one question in, five screens out.

A starter reads what Home Assistant already knows about a system and turns it
into page configuration. It exists so a new user gets useful screens without
learning the page schema first.

Two rules hold for every starter:

* A starter only ever writes page configuration. It never talks to the device
  and never touches the Display source select, so the coordinator's
  push-suppression invariant holds by construction.
* Generated screens are written once and then become ordinary editable
  configuration. Nothing regenerates them, so an edit is never overwritten.

``async_available`` doubles as the availability check and the label: it returns
a short description of what the starter found, or ``None`` when there is
nothing to build and the starter should stay hidden.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .cards import MAX_SLOTS
from .const import DOMAIN, SCREEN_COUNT
from .defaults import DEFAULT_CLOCK_FACE
from .discovery import async_get_per_screen_face_catalog

_LOGGER = logging.getLogger(__name__)

OFF_PAGE: dict[str, Any] = {"page_type": "off"}

# Divoom's own category names, as returned by Channel/GetDialType.
_NORMAL_CATEGORY = "Normal"

_FACE_CACHE_KEY = "starter_clock_face"


@dataclass(frozen=True)
class Starter:
    """One way to fill screens from what Home Assistant already knows."""

    key: str
    name: str
    screens: int  # 1 for a single screen, SCREEN_COUNT for a whole set
    async_available: Callable[[HomeAssistant], Awaitable[str | None]]
    # One entry per screen. A screen is a page dict, or a list of pages that
    # rotate, exactly as the options flow stores it.
    async_build: Callable[[HomeAssistant], Awaitable[list[Any]]]


def pad(pages: list[Any]) -> list[Any]:
    """Return exactly ``SCREEN_COUNT`` screens, padding with off pages."""
    filled = list(pages[:SCREEN_COUNT])
    while len(filled) < SCREEN_COUNT:
        filled.append(dict(OFF_PAGE))
    return filled


def clock_page(clock_id: int = DEFAULT_CLOCK_FACE) -> dict[str, Any]:
    """A native device face. The device draws it, Home Assistant does not."""
    return {"page_type": "clock", "clock_id": clock_id}


async def _pick_clock_face(hass: HomeAssistant) -> int:
    """Choose a face id that is still in Divoom's catalog right now."""
    catalog = await async_get_per_screen_face_catalog(async_get_clientsession(hass))
    if not catalog:
        _LOGGER.debug("Face catalog unavailable, using face %s", DEFAULT_CLOCK_FACE)
        return DEFAULT_CLOCK_FACE
    if any(DEFAULT_CLOCK_FACE in ids for ids in catalog.values()):
        return DEFAULT_CLOCK_FACE
    # "Normal" holds the ordinary clocks. "Pixel Art" is skipped on purpose: it
    # carries the Custom, Visualizer and Cloud Channel slots, which stay blank
    # until they are configured in the Divoom app.
    if normal := catalog.get(_NORMAL_CATEGORY):
        chosen = next(iter(normal))
        _LOGGER.debug(
            "Face %s is gone from the catalog, using %s instead",
            DEFAULT_CLOCK_FACE,
            chosen,
        )
        return chosen
    _LOGGER.debug("No Normal faces in the catalog, using face %s", DEFAULT_CLOCK_FACE)
    return DEFAULT_CLOCK_FACE


async def async_clock_face(hass: HomeAssistant) -> int:
    """The face a generated clock screen gets, resolved once per Home Assistant.

    Divoom can retire a face, and the shipped default was only ever verified on
    one device, so the id is checked against the live catalog instead of being
    trusted forever. Be clear about what that buys: ``Channel/GetDialType`` and
    ``Channel/GetDialList`` take no DeviceId, so the catalog is the same for
    every LCD device. This guarantees the id still exists today. It is not
    evidence that the face renders well on a given hardware revision.

    The cloud not answering is not an error here. Setup falls back to the
    shipped default and carries on.
    """
    cache: dict[str, Any] = hass.data.setdefault(DOMAIN, {})
    cached = cache.get(_FACE_CACHE_KEY)
    if cached is None:
        cached = cache[_FACE_CACHE_KEY] = await _pick_clock_face(hass)
    return int(cached)


async def async_clock_page(hass: HomeAssistant) -> dict[str, Any]:
    """A native clock page on a face that is still in today's catalog."""
    return clock_page(await async_clock_face(hass))


def sensor_card(
    name: str, slots: list[dict[str, Any]], theme: str = "dark"
) -> dict[str, Any]:
    """A sensor_grid card page, the layout every starter builds its values on."""
    return {
        "page_type": "card",
        "card": "sensor_grid",
        "name": name,
        "theme": theme,
        "slots": slots,
    }


# --- energy ----------------------------------------------------------------


def describe_energy(found: Any) -> str | None:
    """Name the energy sources found, or ``None`` when there are none."""
    parts = []
    if found.price_now:
        parts.append("price")
    if found.has_solar:
        parts.append("solar")
    if found.has_battery:
        parts.append("battery")
    if found.has_electricity:
        parts.append("grid")
    if found.gas_stat:
        parts.append("gas")
    if found.water_stats:
        parts.append("water")
    return ", ".join(parts) or None


async def _energy_available(hass: HomeAssistant) -> str | None:
    from .energy import async_discover

    return describe_energy(await async_discover(hass))


async def _energy_build(hass: HomeAssistant) -> list[Any]:
    from .presets import async_build_energy_preset

    return pad(await async_build_energy_preset(hass))


# --- clock and weather -----------------------------------------------------


def first_entity(hass: HomeAssistant, domain: str) -> str | None:
    """The first entity id in ``domain``, sorted so the pick is stable."""
    ids = sorted(state.entity_id for state in hass.states.async_all(domain))
    return ids[0] if ids else None


def weather_slots(entity_id: str) -> list[dict[str, Any]]:
    """Temperature and humidity read off a weather entity's attributes.

    A weather entity's state is a condition word, not a number, so both values
    come from attributes through a template.
    """
    return [
        {
            "name": "Outside",
            "entity_id": entity_id,
            "icon": "mdi:thermometer",
            "value_template": (
                f"{{{{ state_attr('{entity_id}', 'temperature') | round(0) }}}}"
            ),
        },
        {
            "name": "Humidity",
            "entity_id": entity_id,
            "icon": "mdi:water-percent",
            "value_template": (
                f"{{{{ state_attr('{entity_id}', 'humidity') | round(0) }}}}"
            ),
        },
    ]


async def _clock_weather_available(hass: HomeAssistant) -> str | None:
    entity_id = first_entity(hass, "weather")
    return f"clock, {entity_id}" if entity_id else "clock"


async def _clock_weather_build(hass: HomeAssistant) -> list[Any]:
    pages = [await async_clock_page(hass)]
    if entity_id := first_entity(hass, "weather"):
        pages.append(sensor_card("Weather", weather_slots(entity_id)))
    return pad(pages)


# --- single-screen starters ------------------------------------------------
#
# These fill one screen, so they show up both in the setup picker and in a
# screen's own menu under "Fill from a template". They stay close to plain
# entity_id slots wherever they can, because a slot that only names an entity
# is one the per-screen form can still edit afterwards.

_OUTDOOR_WORDS = (
    "outdoor",
    "outside",
    "garden",
    "balcony",
    "terrace",
    "buiten",
    "tuin",
)


def _area_name(hass: HomeAssistant, entity_id: str) -> str:
    """The area an entity sits in, through its device when it has no area."""
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    entry = er.async_get(hass).async_get(entity_id)
    if entry is None:
        return ""
    area_id = entry.area_id
    if area_id is None and entry.device_id:
        device = dr.async_get(hass).async_get(entry.device_id)
        area_id = device.area_id if device else None
    if area_id is None:
        return ""
    area = ar.async_get(hass).async_get_area(area_id)
    return area.name if area else ""


def _is_outdoor(hass: HomeAssistant, entity_id: str) -> bool:
    area = _area_name(hass, entity_id).lower()
    return any(word in area for word in _OUTDOOR_WORDS)


def _by_device_class(hass: HomeAssistant, domain: str, *classes: str) -> list[str]:
    """Entity ids in ``domain`` carrying one of these device classes."""
    wanted = set(classes)
    return sorted(
        state.entity_id
        for state in hass.states.async_all(domain)
        if state.attributes.get("device_class") in wanted
    )


def _slots(entity_ids: list[str]) -> list[dict[str, Any]]:
    """Plain slots, so the per-screen form can still edit what is generated."""
    return [{"entity_id": entity_id} for entity_id in entity_ids[:MAX_SLOTS]]


async def _weather_available(hass: HomeAssistant) -> str | None:
    return first_entity(hass, "weather")


async def _weather_build(hass: HomeAssistant) -> list[Any]:
    entity_id = first_entity(hass, "weather")
    if entity_id is None:
        return [dict(OFF_PAGE)]
    return [sensor_card("Weather", weather_slots(entity_id))]


def _climate_air_entities(hass: HomeAssistant) -> list[str]:
    """Room comfort, indoors first, because that is what people look at."""
    found = [state.entity_id for state in hass.states.async_all("climate")]
    found += _by_device_class(
        hass, "sensor", "temperature", "humidity", "carbon_dioxide"
    )
    indoor = [entity_id for entity_id in found if not _is_outdoor(hass, entity_id)]
    outdoor = [entity_id for entity_id in found if _is_outdoor(hass, entity_id)]
    return indoor + outdoor


async def _climate_air_available(hass: HomeAssistant) -> str | None:
    found = _climate_air_entities(hass)
    return f"{len(found)} entities" if found else None


async def _climate_air_build(hass: HomeAssistant) -> list[Any]:
    found = _climate_air_entities(hass)
    if not found:
        return [dict(OFF_PAGE)]
    return [sensor_card("Climate", _slots(found))]


def _presence_entities(hass: HomeAssistant) -> list[str]:
    """Who is home, and what is standing open while they are not."""
    found = [state.entity_id for state in hass.states.async_all("person")]
    if not found:
        found = [state.entity_id for state in hass.states.async_all("device_tracker")]
    found += [state.entity_id for state in hass.states.async_all("alarm_control_panel")]
    found += _by_device_class(hass, "binary_sensor", "door", "window")
    return found


async def _presence_available(hass: HomeAssistant) -> str | None:
    found = _presence_entities(hass)
    return f"{len(found)} entities" if found else None


async def _presence_build(hass: HomeAssistant) -> list[Any]:
    found = _presence_entities(hass)
    if not found:
        return [dict(OFF_PAGE)]
    return [sensor_card("Presence", _slots(found))]


def _native_clock_page() -> dict[str, Any]:
    """A clock the device draws itself, out of ``NATIVE_KIND_TYPES``."""
    return {
        "page_type": "dispdata_text",
        "items": [
            {"kind": "time_short", "x": 0, "y": 30, "font": 4, "align": 3},
            {"kind": "weekday_full", "x": 0, "y": 66, "align": 3},
            {"kind": "month_day", "x": 0, "y": 86, "align": 3},
        ],
    }


def _calendar_slots(hass: HomeAssistant) -> list[dict[str, Any]]:
    """The next event per calendar. A calendar's state is on or off, so the
    title has to come out of its attributes."""
    slots = []
    for state in sorted(hass.states.async_all("calendar"), key=lambda s: s.entity_id):
        slots.append(
            {
                "name": state.name,
                "entity_id": state.entity_id,
                "icon": "mdi:calendar",
                "value_template": (
                    f"{{{{ state_attr('{state.entity_id}', 'message') or '-' }}}}"
                ),
            }
        )
    return slots[:MAX_SLOTS]


async def _calendar_clock_available(hass: HomeAssistant) -> str | None:
    slots = _calendar_slots(hass)
    return f"clock, {len(slots)} calendars" if slots else None


async def _calendar_clock_build(hass: HomeAssistant) -> list[Any]:
    pages: list[dict[str, Any]] = [{**_native_clock_page(), "duration": 20}]
    if slots := _calendar_slots(hass):
        pages.append({**sensor_card("Agenda", slots), "duration": 20})
    return [pages]  # one screen rotating through its pages


STARTERS: tuple[Starter, ...] = (
    Starter(
        key="energy",
        name="Energy",
        screens=SCREEN_COUNT,
        async_available=_energy_available,
        async_build=_energy_build,
    ),
    Starter(
        key="clock_weather",
        name="Clock and weather",
        screens=SCREEN_COUNT,
        async_available=_clock_weather_available,
        async_build=_clock_weather_build,
    ),
    Starter(
        key="weather",
        name="Weather",
        screens=1,
        async_available=_weather_available,
        async_build=_weather_build,
    ),
    Starter(
        key="climate_air",
        name="Climate and air",
        screens=1,
        async_available=_climate_air_available,
        async_build=_climate_air_build,
    ),
    Starter(
        key="presence",
        name="Presence",
        screens=1,
        async_available=_presence_available,
        async_build=_presence_build,
    ),
    Starter(
        key="calendar_clock",
        name="Calendar and clock",
        screens=1,
        async_available=_calendar_clock_available,
        async_build=_calendar_clock_build,
    ),
)


def get_starter(key: str) -> Starter | None:
    """Look a starter up by key."""
    return next((s for s in STARTERS if s.key == key), None)


async def async_available_starters(
    hass: HomeAssistant, *, screens: int | None = None
) -> list[tuple[Starter, str]]:
    """Every starter that found something, in registry order.

    Pass ``screens=1`` to keep only the starters that fill a single screen.
    The returned description is what that starter found, ready to show.
    """
    available: list[tuple[Starter, str]] = []
    for starter in STARTERS:
        if screens is not None and starter.screens != screens:
            continue
        if found := await starter.async_available(hass):
            available.append((starter, found))
    return available
