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
        today = f"(state_attr('{forecast}', 'prices_today') or [])"
        panel["price_min_template"] = (
            f"{{{{ {today} | map(attribute='price') | list | min | default(0) }}}}"
        )
        panel["price_max_template"] = (
            f"{{{{ {today} | map(attribute='price') | list | max | default(0) }}}}"
        )
    graph: dict[str, Any] = {
        "page_type": "card",
        "card": "graph",
        "name": "Day ahead",
        "style": "bar",
        "color": "#4ADE80",
        "high_color": "#EF4444",
        "entity_id": found.price_now,
        "value": True,
        "footer_height": 32,
        "footer_slots": [],
    }
    if forecast:
        graph["data_template"] = f"{{{{ {prices} }}}}"
    return panel, graph


def _footer_slot(stat: str, name: str, color: str, unit: str) -> dict[str, Any]:
    """Describe one footer value, polled live where possible.

    A statistic id without a dot has no entity behind it, which is how gas
    usually arrives. The device cannot poll that, so the slot falls back to
    today's total read from long-term statistics and drawn into the artwork.
    """
    if "." in stat:
        return {"entity_id": stat, "name": name, "color": color}
    return {"stat": stat, "name": name, "color": color, "unit": unit}


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

    battery: dict[str, Any] = (
        {
            "page_type": "card",
            "card": "energy_panel",
            "mode": "battery",
            "name": "Battery",
            "entity_id": found.battery_soc,
            "power_entity": found.battery_power,
            "battery_power_entity": found.battery_power,
        }
        if found.has_battery
        else {"page_type": "off"}
    )

    solar: dict[str, Any] = (
        {
            "page_type": "card",
            "card": "energy_panel",
            "mode": "solar",
            "name": "Solar",
            "entity_id": found.solar_power,
            "solar_power_entity": found.solar_power,
            "solar_stat": found.solar_stat,
            "color": ENERGY_COLORS["solar"],
        }
        if found.has_solar
        else {"page_type": "off"}
    )

    footer: list[dict[str, Any]] = []
    if found.gas_stat:
        footer.append(_footer_slot(found.gas_stat, "Gas", ENERGY_COLORS["gas"], "m³"))
    for stat in found.water_stats:
        footer.append(_footer_slot(stat, "Water", ENERGY_COLORS["water"], "L"))
        break
    price_graph["footer_slots"] = footer
    if not footer:
        price_graph["footer_height"] = 0

    return [price_panel, power, battery, solar, price_graph]


async def async_build_energy_preset(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Discover the energy configuration and turn it into five screens."""
    from .energy import async_discover

    return build_energy_preset(await async_discover(hass))


def with_energy_preset(
    options: dict[str, Any], screens: list[dict[str, Any]]
) -> dict[str, Any]:
    """Store ``screens`` as the energy preset and make it active."""
    presets = dict(options.get(CONF_PRESETS) or {})
    if CONF_SCREENS in options and DEFAULT_PRESET not in presets:
        presets[DEFAULT_PRESET] = list(options[CONF_SCREENS] or [])
    presets[ENERGY_PRESET] = screens
    return {**options, CONF_PRESETS: presets, CONF_ACTIVE_PRESET: ENERGY_PRESET}
