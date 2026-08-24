"""Named screen sets, and the generator that builds the energy one.

A preset is a list of five page configs. Switching preset swaps every screen at
once, so one device can carry an energy view, a night view and whatever else
without editing the configuration each time.

The energy preset is generated once from the Home Assistant energy dashboard
configuration and then stored as an ordinary preset, so you can edit any screen
afterwards without the generator overwriting your changes.
"""
from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACTIVE_PRESET,
    CONF_PRESETS,
    CONF_SCREENS,
    DEFAULT_PRESET,
    ENERGY_COLORS,
    ENERGY_PRESET,
)
from .energy import EnergySources, house_power_template


def read_presets(options: dict[str, Any]) -> dict[str, list[Any]]:
    """Return every preset, folding a pre-preset ``screens`` list into one.

    Configurations written before presets existed keep working: their screens
    become the ``default`` preset.
    """
    presets: dict[str, list[Any]] = {}
    for name, screens in (options.get(CONF_PRESETS) or {}).items():
        if isinstance(screens, list):
            presets[str(name)] = list(screens)
    if screens := options.get(CONF_SCREENS):
        presets.setdefault(DEFAULT_PRESET, list(screens))
    return presets


def describe_page(page: Any) -> str:
    """A few words naming what a screen holds, for the options menu."""
    if isinstance(page, list):
        if not page:
            return "empty"
        parts = [describe_page(item) for item in page]
        return " + ".join(parts)
    if not isinstance(page, dict):
        return "empty"
    kind = str(page.get("page_type") or "components")
    if kind == "card":
        return str(page.get("card") or "card")
    if kind == "graph":
        return str(page.get("title") or "graph")
    if kind == "energy_panel":
        return str(page.get("mode") or "energy")
    if kind == "image":
        return "image"
    return kind


def active_screens(options: dict[str, Any]) -> list[Any]:
    """The screen list for whichever preset is active."""
    presets = read_presets(options)
    if not presets:
        return list(options.get(CONF_SCREENS) or [])
    name = str(options.get(CONF_ACTIVE_PRESET) or "")
    if name in presets:
        return presets[name]
    if DEFAULT_PRESET in presets:
        return presets[DEFAULT_PRESET]
    return next(iter(presets.values()))


def _history_page(found: EnergySources) -> dict[str, Any]:
    """The 24 hour history graph for screen five, or an off page.

    Two series: solar production per hour from the solar statistic, and house
    consumption per hour derived from the grid and battery statistics the house
    panel already sums. The graph needs at least one of those to draw, so a home
    with neither solar nor a grid statistic gets a blank screen rather than an
    empty axis.
    """
    grid_stats = [
        found.grid_import_stat,
        found.grid_export_stat,
        found.battery_in_stat,
        found.battery_out_stat,
    ]
    has_consumption = any(grid_stats)
    if not found.solar_stat and not has_consumption:
        return {"page_type": "off"}
    return {
        "page_type": "card",
        "card": "energy_history",
        "title": "Today",
        "unit": "kWh",
        "solar_stat": found.solar_stat,
        "import_stat": found.grid_import_stat,
        "export_stat": found.grid_export_stat,
        "battery_in_stat": found.battery_in_stat,
        "battery_out_stat": found.battery_out_stat,
        "solar_color": ENERGY_COLORS["solar"],
        "consumption_color": "#FFFFFF",
    }


def _price_pages(found: EnergySources) -> tuple[dict[str, Any], dict[str, Any]]:
    """The current-price panel and the day-ahead price graph."""
    forecast = found.price_forecast
    prices = f"state_attr('{forecast}', 'prices')" if forecast else "[]"
    panel: dict[str, Any] = {
        "page_type": "card",
        "card": "energy_panel",
        "mode": "price",
        "name": "Price",
        "entity_id": found.price_now,
        "unit": "EUR/kWh",
    }
    if forecast:
        # Some forecast sensors publish only `prices`, which may run past
        # midnight. Prefer today's list and fall back rather than leaving the
        # range at zero, which would draw a confident 0.000 to 0.000 bar.
        series = (
            f"((state_attr('{forecast}', 'prices_today') or "
            f"state_attr('{forecast}', 'prices') or []) "
            f"| map(attribute='price') | list)"
        )
        panel["price_min_template"] = f"{{{{ {series} | min | default('') }}}}"
        panel["price_max_template"] = f"{{{{ {series} | max | default('') }}}}"
        # Knowing the price is 0.03 is half the information; knowing it lands at
        # 13:00 is the half that changes behaviour. Sort the same list by price
        # and read the time off the cheapest and priciest entry. A missing or
        # malformed list renders empty, and the drawer then draws nothing.
        entries = (
            f"((state_attr('{forecast}', 'prices_today') or "
            f"state_attr('{forecast}', 'prices') or []) "
            f"| selectattr('price', 'defined') | list)"
        )
        panel["cheapest_time_template"] = (
            f"{{% set p = {entries} %}}"
            "{% if p %}"
            "{{ ((p | sort(attribute='price') | first).time | as_datetime | as_local).strftime('%H:%M') }}"
            "{% endif %}"
        )
        panel["priciest_time_template"] = (
            f"{{% set p = {entries} %}}"
            "{% if p %}"
            "{{ ((p | sort(attribute='price') | last).time | as_datetime | as_local).strftime('%H:%M') }}"
            "{% endif %}"
        )
    graph: dict[str, Any] = {
        "page_type": "card",
        "card": "graph",
        "title": "Day ahead",
        "style": "bar",
        "color": "#4ADE80",
        "high_color": "#EF4444",
        "marker": "now",
        "x_labels": True,
        "unit": "EUR/kWh",
        "entity_id": found.price_now,
        "value": True,
    }
    if forecast:
        graph["data_template"] = f"{{{{ {prices} }}}}"
    return panel, graph


def _footer_slot(stat: str, name: str, color: str, unit: str) -> dict[str, Any]:
    """Describe one footer value as today's consumption.

    Gas and water meters report a running total, so polling the entity live
    would show the meter reading rather than what the house used today. Read
    today's change out of long-term statistics instead, and keep the entity id
    as a fallback for a sensor the recorder has no statistics for.
    """
    slot: dict[str, Any] = {"stat": stat, "name": name, "color": color, "unit": unit}
    if "." in stat:
        slot["entity_id"] = stat
    return slot


def build_energy_preset(found: EnergySources) -> list[dict[str, Any]]:
    """Build the five energy screens from the discovered sources.

    Screens without a matching source fall back to an off page rather than
    rendering an empty panel, so a home without a battery gets four screens and
    a blank one instead of a broken one.
    """
    price_panel, price_graph = _price_pages(found)

    power: dict[str, Any] = {
        "page_type": "card",
        "card": "energy_panel",
        "mode": "power",
        "name": "House",
        "value_template": house_power_template(found),
        "import_entity": found.grid_import_power,
        "export_entity": found.grid_export_power,
        "import_stat": found.grid_import_stat,
        "export_stat": found.grid_export_stat,
        "import_color": ENERGY_COLORS["grid_import"],
        "export_color": ENERGY_COLORS["grid_export"],
    }

    solar_battery = _solar_battery_page(found)

    # Gas and water sit on the house screen now, not on the price graph. Build
    # the footer once and give it to the house panel; the price graph goes back
    # to full height. Graceful omit stays: no slots means no band.
    footer: list[dict[str, Any]] = []
    if found.gas_stat:
        footer.append(_footer_slot(found.gas_stat, "Gas", ENERGY_COLORS["gas"], "m³"))
    for stat in found.water_stats:
        footer.append(_footer_slot(stat, "Water", ENERGY_COLORS["water"], "L"))
        break
    if footer:
        power["footer_slots"] = footer
        power["footer_height"] = 32

    history = _history_page(found)

    # Solar and battery share one screen, so the fifth slot carries the 24 hour
    # history graph. It falls back to off when there is nothing to draw.
    return [price_panel, power, solar_battery, price_graph, history]


def _solar_battery_page(found: EnergySources) -> dict[str, Any]:
    """The merged solar-and-battery screen, or an off page when neither exists.

    The drawer chooses its own layout from the fields present: solar only,
    battery only, or both. It only needs a page here when at least one side has
    a source, so a home with neither still gets a blank screen instead of a
    broken one.
    """
    if not found.has_solar and not found.has_battery:
        return {"page_type": "off"}
    page: dict[str, Any] = {
        "page_type": "card",
        "card": "energy_panel",
        "mode": "solar_battery",
        "name": "Energy",
        # A static goal of 0 means "no goal", so the solar half keeps its plain
        # "x kWh today" caption. async_build_energy_preset fills goal_template in
        # when it finds a Forecast.Solar production-today sensor.
        "goal": 0,
    }
    if found.has_solar:
        page.update(
            {
                "entity_id": found.solar_power,
                "solar_power_entity": found.solar_power,
                "solar_stat": found.solar_stat,
                "color": ENERGY_COLORS["solar"],
            }
        )
    if found.has_battery:
        page.update(
            {
                "battery_soc": found.battery_soc,
                "power_entity": found.battery_power,
                "battery_power_entity": found.battery_power,
            }
        )
        if not found.has_solar:
            # Battery only: the hero is the state of charge, so point the panel's
            # value entity at the SoC sensor.
            page["entity_id"] = found.battery_soc
    # Name the single-source fallbacks after what they draw, and keep the
    # neutral "Energy" for the merged layout.
    if found.has_solar and not found.has_battery:
        page["name"] = "Solar"
    elif found.has_battery and not found.has_solar:
        page["name"] = "Battery"
    return page


def _forecast_solar_goal_template(hass: HomeAssistant, found: EnergySources) -> str | None:
    """A goal template pointing at a solar forecast production-today sensor.

    The energy configuration already records which config entries produce the
    solar forecast, so resolve those entry ids to an entity rather than guessing
    one from a platform name. Match a ``energy_production_today`` suffix on
    either the entity id or the unique id so a forecast entity with another
    suffix cannot stand in for it.
    """
    if not found.solar_forecast_entries:
        return None

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    for entry_id in found.solar_forecast_entries:
        for entry in er.async_entries_for_config_entry(registry, entry_id):
            unique_id = entry.unique_id or ""
            if entry.entity_id.endswith("energy_production_today") or unique_id.endswith(
                "energy_production_today"
            ):
                return f"{{{{ states('{entry.entity_id}') | float(0) }}}}"
    return None


async def async_build_energy_preset(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Discover the energy configuration and turn it into five screens."""
    from .energy import async_discover

    found = await async_discover(hass)
    screens = build_energy_preset(found)
    if template := _forecast_solar_goal_template(hass, found):
        for page in screens:
            if page.get("mode") == "solar_battery":
                page["goal_template"] = template
    return screens


def with_energy_preset(
    options: dict[str, Any], screens: list[dict[str, Any]]
) -> dict[str, Any]:
    """Store ``screens`` as the energy preset and make it active."""
    presets = dict(options.get(CONF_PRESETS) or {})
    if CONF_SCREENS in options and DEFAULT_PRESET not in presets:
        presets[DEFAULT_PRESET] = list(options[CONF_SCREENS] or [])
    presets[ENERGY_PRESET] = screens
    return {**options, CONF_PRESETS: presets, CONF_ACTIVE_PRESET: ENERGY_PRESET}
