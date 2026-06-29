"""Default screen configuration.

The 5 defaults mirror the author's setup and render at native 128x128 with
scalable fonts (``font`` given as an integer pixel size, mixed-case text). The
same page schema also supports Pixoo-style bitmap fonts (``font: pico_8`` etc.)
on a 64 canvas (``size: 64``) for drop-in portability with
gickowtf/pixoo-homeassistant configs.
"""
from __future__ import annotations

from typing import Any

_HAME = "sensor.hame_energy_hmg_50_acd929a74998"
_NETATMO = "sensor.netatmo_weather_station"
_OUT = f"{_NETATMO}_netatmo_outdoor_module_temperatuur"

DEFAULT_SCREENS: list[dict[str, Any]] = [
    {
        "page_type": "components",
        "size": 128,
        "variables": {
            "soc": f"{{{{ states('{_HAME}_battery_state_of_charge')|int }}}}",
            "col": (
                f"{{% set s = states('{_HAME}_battery_state_of_charge')|int %}}"
                "{% if s < 20 %}red{% elif s < 50 %}orange{% else %}green{% endif %}"
            ),
        },
        "components": [
            {"type": "text", "content": "HOME BATTERY", "position": [64, 6], "align": "center", "font": 13, "color": "gray"},
            {"type": "text", "content": "{{ soc }}%", "position": [64, 26], "align": "center", "font": 42, "color": "{{ col }}"},
            {"type": "rectangle", "position": [20, 84], "size": [88, 12], "color": [80, 80, 80], "filled": False},
            {"type": "rectangle", "position": [21, 85], "size": ["{{ (soc|int * 86 / 100)|int }}", 10], "color": "{{ col }}", "filled": True},
            {"type": "text", "content": "{{ states('" + _HAME + "_combined_power')|int }}W", "position": [64, 104], "align": "center", "font": 13, "color": "white"},
        ],
    },
    {
        "page_type": "components",
        "size": 128,
        "components": [
            {"type": "text", "content": "SOLAR", "position": [64, 6], "align": "center", "font": 13, "color": "gray"},
            {"type": "text", "content": "{{ states('sensor.solaredge_i1_ac_power')|int }} W", "position": [64, 38], "align": "center", "font": 30, "color": "yellow"},
            {"type": "text", "content": "Today {{ states('sensor.energy_production_today')|round(1) }} kWh", "position": [64, 100], "align": "center", "font": 13, "color": "white"},
        ],
    },
    {
        "page_type": "components",
        "size": 128,
        "variables": {
            "net": (
                "{{ ((states('sensor.energyhome_electrical_power_from_grid')|float"
                " - states('sensor.energyhome_electrical_power_to_grid')|float)|abs"
                " / 1000)|round(2) }}"
            ),
        },
        "components": [
            {"type": "text", "content": "GRID POWER", "position": [64, 6], "align": "center", "font": 13, "color": "gray"},
            {"type": "text", "content": "{{ net }}", "position": [64, 28], "align": "center", "font": 40, "color": "blue"},
            {"type": "text", "content": "kW", "position": [64, 74], "align": "center", "font": 13, "color": "gray"},
            {"type": "text", "content": "Month {{ states('sensor.energy_monthly')|round(0) }} kWh", "position": [64, 102], "align": "center", "font": 13, "color": "white"},
        ],
    },
    {
        "page_type": "components",
        "size": 128,
        "components": [
            {"type": "text", "content": "CLIMATE", "position": [64, 4], "align": "center", "font": 12, "color": "gray"},
            {"type": "text", "content": "IN {{ states('" + _NETATMO + "_temperatuur')|round(1) }}C", "position": [64, 20], "align": "center", "font": 24, "color": "white"},
            {"type": "text", "content": "{{ states('" + _NETATMO + "_luchtvochtigheid')|int }}% RH", "position": [64, 52], "align": "center", "font": 12, "color": "gray"},
            {"type": "rectangle", "position": [16, 72], "size": [96, 1], "color": [60, 60, 60], "filled": True},
            {"type": "text", "content": "OUT {{ states('" + _OUT + "')|round(1) }}C", "position": [64, 80], "align": "center", "font": 22, "color": "blue"},
            {"type": "text", "content": "CO2 {{ states('" + _NETATMO + "_kooldioxide')|int }} ppm", "position": [64, 110], "align": "center", "font": 11, "color": "gray"},
        ],
    },
    {
        "page_type": "components",
        "size": 128,
        "components": [
            {"type": "text", "content": "WEATHER", "position": [64, 6], "align": "center", "font": 13, "color": "gray"},
            {"type": "text", "content": "{{ states('weather.forecast_thuis_boom')|upper|replace('-',' ') }}", "position": [64, 36], "align": "center", "font": 16, "color": "cyan"},
            {"type": "text", "content": "{{ states('" + _OUT + "')|round(1) }}C", "position": [64, 62], "align": "center", "font": 26, "color": "white"},
        ],
    },
]
