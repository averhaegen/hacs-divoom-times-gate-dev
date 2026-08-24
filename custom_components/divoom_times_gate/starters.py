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
from typing import Any

from homeassistant.core import HomeAssistant

from .const import SCREEN_COUNT
from .defaults import DEFAULT_CLOCK_FACE

OFF_PAGE: dict[str, Any] = {"page_type": "off"}


@dataclass(frozen=True)
class Starter:
    """One way to fill screens from what Home Assistant already knows."""

    key: str
    name: str
    screens: int  # 1 for a single screen, SCREEN_COUNT for a whole set
    async_available: Callable[[HomeAssistant], Awaitable[str | None]]
    async_build: Callable[[HomeAssistant], Awaitable[list[dict[str, Any]]]]


def pad(pages: list[Any]) -> list[Any]:
    """Return exactly ``SCREEN_COUNT`` screens, padding with off pages."""
    filled = list(pages[:SCREEN_COUNT])
    while len(filled) < SCREEN_COUNT:
        filled.append(dict(OFF_PAGE))
    return filled


def clock_page(clock_id: int = DEFAULT_CLOCK_FACE) -> dict[str, Any]:
    """A native device face. The device draws it, Home Assistant does not."""
    return {"page_type": "clock", "clock_id": clock_id}


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


async def _energy_build(hass: HomeAssistant) -> list[dict[str, Any]]:
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


async def _clock_weather_build(hass: HomeAssistant) -> list[dict[str, Any]]:
    pages = [clock_page()]
    if entity_id := first_entity(hass, "weather"):
        pages.append(sensor_card("Weather", weather_slots(entity_id)))
    return pad(pages)


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
