"""Default screen configuration, in the Pixoo-compatible component schema.

These 5 screens mirror the author's setup and double as worked examples of the
portable page format (page_type: components, 64x64 canvas scaled to 128). Users
edit them via the options flow (YAML). A page copied from a Pixoo config will
render here unchanged.
"""
from __future__ import annotations

from typing import Any

_HAME = "sensor.hame_energy_hmg_50_acd929a74998"
_NETATMO = "sensor.netatmo_weather_station"

DEFAULT_SCREENS: list[dict[str, Any]] = [
    {
        "page_type": "components",
        "size": 64,
        "variables": {
            "soc": f"{{{{ states('{_HAME}_battery_state_of_charge')|int }}}}",
            "col": (
                f"{{% set s = states('{_HAME}_battery_state_of_charge')|int %}}"
                "{% if s < 20 %}red{% elif s < 50 %}orange{% else %}green{% endif %}"
            ),
        },
        "components": [
            {"type": "text", "content": "HOME BATTERY", "position": [32, 3], "align": "center", "font": "pico_8", "color": "gray"},
            {"type": "text", "content": "{{ soc }}%", "position": [32, 14], "align": "center", "font": "pix24", "color": "{{ col }}"},
            {"type": "rectangle", "position": [10, 44], "size": [44, 7], "color": [80, 80, 80], "filled": False},
            {"type": "rectangle", "position": [11, 45], "size": ["{{ (soc|int * 42 / 100)|int }}", 5], "color": "{{ col }}", "filled": True},
            {"type": "text", "content": "{{ states('" + _HAME + "_combined_power')|int }}W", "position": [32, 55], "align": "center", "font": "pico_8", "color": "white"},
        ],
    },
    {
        "page_type": "components",
        "size": 64,
        "components": [
            {"type": "text", "content": "SOLAR", "position": [32, 3], "align": "center", "font": "pico_8", "color": "gray"},
            {"type": "text", "content": "{{ states('sensor.solaredge_i1_ac_power')|int }}W", "position": [32, 20], "align": "center", "font": "eleven_pix", "color": "yellow"},
            {"type": "text", "content": "TODAY {{ states('sensor.energy_production_today')|round(1) }}", "position": [32, 48], "align": "center", "font": "pico_8", "color": "white"},
            {"type": "text", "content": "KWH", "position": [32, 56], "align": "center", "font": "pico_8", "color": "gray"},
        ],
    },
    {
        "page_type": "components",
        "size": 64,
        "variables": {
            "net": (
                "{{ ((states('sensor.energyhome_electrical_power_from_grid')|float"
                " - states('sensor.energyhome_electrical_power_to_grid')|float)|abs"
                " / 1000)|round(2) }}"
            ),
        },
        "components": [
            {"type": "text", "content": "GRID", "position": [32, 3], "align": "center", "font": "pico_8", "color": "gray"},
            {"type": "text", "content": "{{ net }}", "position": [32, 16], "align": "center", "font": "pix24", "color": "blue"},
            {"type": "text", "content": "KW", "position": [32, 42], "align": "center", "font": "pico_8", "color": "gray"},
            {"type": "text", "content": "MONTH {{ states('sensor.energy_monthly')|round(0) }}", "position": [32, 55], "align": "center", "font": "pico_8", "color": "white"},
        ],
    },
    {
        "page_type": "components",
        "size": 64,
        "components": [
            {"type": "text", "content": "CLIMATE", "position": [32, 2], "align": "center", "font": "pico_8", "color": "gray"},
            {"type": "text", "content": "IN {{ states('" + _NETATMO + "_temperatuur')|round(1) }}C", "position": [32, 13], "align": "center", "font": "eleven_pix", "color": "white"},
            {"type": "text", "content": "{{ states('" + _NETATMO + "_luchtvochtigheid')|int }}% RH", "position": [32, 27], "align": "center", "font": "pico_8", "color": "gray"},
            {"type": "rectangle", "position": [8, 35], "size": [48, 1], "color": [51, 51, 51], "filled": True},
            {"type": "text", "content": "OUT {{ states('" + _NETATMO + "_netatmo_outdoor_module_temperatuur')|round(1) }}C", "position": [32, 40], "align": "center", "font": "eleven_pix", "color": "blue"},
            {"type": "text", "content": "CO2 {{ states('" + _NETATMO + "_kooldioxide')|int }}", "position": [32, 55], "align": "center", "font": "pico_8", "color": "gray"},
        ],
    },
    {
        "page_type": "components",
        "size": 64,
        "components": [
            {"type": "text", "content": "WEATHER", "position": [32, 3], "align": "center", "font": "pico_8", "color": "gray"},
            {"type": "text", "content": "{{ states('weather.forecast_thuis_boom')|replace('-',' ') }}", "position": [32, 22], "align": "center", "font": "eleven_pix", "color": "cyan"},
            {"type": "text", "content": "{{ states('" + _NETATMO + "_netatmo_outdoor_module_temperatuur')|round(1) }}C", "position": [32, 42], "align": "center", "font": "gicko", "color": "white"},
        ],
    },
]
