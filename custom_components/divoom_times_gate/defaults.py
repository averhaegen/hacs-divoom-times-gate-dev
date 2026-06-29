"""Default screen configuration.

POC default mirrors the author's 5 screens. Users edit this via the options
flow (YAML). Each entry is a screen config consumed by ``screens.py`` /
``coordinator.py``.
"""
from __future__ import annotations

from typing import Any

_HAME = "sensor.hame_energy_hmg_50_acd929a74998"
_NETATMO = "sensor.netatmo_weather_station"

DEFAULT_SCREENS: list[dict[str, Any]] = [
    {
        "type": "custom",
        "layout": "bar",
        "title": "HOME BATTERY",
        "value": f"{{{{ states('{_HAME}_battery_state_of_charge')|int }}}}%",
        "bar_pct": f"{{{{ states('{_HAME}_battery_state_of_charge')|int }}}}",
        "sub": f"{{{{ states('{_HAME}_combined_power')|int }}}}W",
        "border": "auto",
        "color_template": (
            f"{{% set s = states('{_HAME}_battery_state_of_charge')|int %}}"
            "{% if s < 20 %}red{% elif s < 50 %}orange{% else %}green{% endif %}"
        ),
    },
    {
        "type": "custom",
        "layout": "big",
        "title": "SOLAR",
        "value": "{{ states('sensor.solaredge_i1_ac_power')|int }} W",
        "sub": "Today {{ states('sensor.energy_production_today')|round(1) }} kWh",
        "border": "yellow",
    },
    {
        "type": "custom",
        "layout": "big",
        "title": "GRID POWER",
        "value": (
            "{{ ((states('sensor.energyhome_electrical_power_from_grid')|float"
            " - states('sensor.energyhome_electrical_power_to_grid')|float)|abs"
            " / 1000)|round(2) }}"
        ),
        "value_size": 44,
        "sub": "Month {{ states('sensor.energy_monthly')|round(0) }} kWh",
        "border": "blue",
    },
    {
        "type": "custom",
        "layout": "dual",
        "title": "CLIMATE",
        "value": f"IN {{{{ states('{_NETATMO}_temperatuur')|round(1) }}}}C",
        "sub": f"{{{{ states('{_NETATMO}_luchtvochtigheid')|int }}}}% RH",
        "value2": f"OUT {{{{ states('{_NETATMO}_netatmo_outdoor_module_temperatuur')|round(1) }}}}C",
        "sub2": f"CO2 {{{{ states('{_NETATMO}_kooldioxide')|int }}}} ppm",
        "border": "blue",
    },
    {
        "type": "custom",
        "layout": "big",
        "title": "WEATHER",
        "value": "{{ states('weather.forecast_thuis_boom')|upper|replace('-',' ') }}",
        "value_size": 16,
        "sub": f"{{{{ states('{_NETATMO}_netatmo_outdoor_module_temperatuur')|round(1) }}}}C",
        "border": "cyan",
    },
]
