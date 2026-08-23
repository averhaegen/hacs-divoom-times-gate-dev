"""Default screen configuration.

The 5 defaults mirror the author's setup and use Pixoo-compatible bitmap fonts
on a 64x64 canvas, which the renderer then scales to the Times Gate's 128x128.
"""
from __future__ import annotations

from typing import Any

# Favorite faces shown in the Select dropdowns. A small starting set — users
# edit these in the options, and grab clock_ids from the Divoom app.
DEFAULT_FACES: dict[str, list[dict[str, Any]]] = {
    "overall": [  # Overall Display (one face spanning all 5 screens)
        {"name": "Neon", "clock_id": 1040},
        {"name": "Clock face", "clock_id": 581},
        {"name": "City Time", "clock_id": 697},
    ],
    "per_screen": [  # single-screen faces (Screen N -> Face: ...)
        {"name": "Weather ONE", "clock_id": 182},
        {"name": "Big Time", "clock_id": 152},
        {"name": "Pinkclock", "clock_id": 669},
        {"name": "DIY Digital Clock", "clock_id": 284},
        {"name": "Retro web cute pastel", "clock_id": 662},
    ],
}

_HAME = "sensor.hame_energy_hmg_50_acd929a74998"
_NETATMO = "sensor.netatmo_weather_station"
_OUT = f"{_NETATMO}_netatmo_outdoor_module_temperatuur"

DEFAULT_SCREENS: list[dict[str, Any]] = [
    {
        "page_type": "components",
        "variables": {
            "soc": f"{{{{ states('{_HAME}_battery_state_of_charge')|int }}}}",
            "col": (
                f"{{% set s = states('{_HAME}_battery_state_of_charge')|int %}}"
                "{% if s < 20 %}red{% elif s < 50 %}orange{% else %}green{% endif %}"
            ),
        },
        "components": [
            {"type": "text", "content": "HOME BATTERY", "position": [32, 2], "align": "center", "font": "pico_8", "color": "gray"},
            {"type": "text", "content": "{{ soc }}%", "position": [32, 14], "align": "center", "font": "eleven_pix", "color": "{{ col }}"},
            {"type": "rectangle", "position": [10, 42], "size": [44, 6], "color": [80, 80, 80], "filled": False},
            {"type": "rectangle", "position": [11, 43], "size": ["{{ (soc|int * 42 / 100)|int }}", 4], "color": "{{ col }}", "filled": True},
            {"type": "text", "content": "{{ states('" + _HAME + "_combined_power')|int }}W", "position": [32, 56], "align": "center", "font": "pico_8", "color": "white"},
        ],
    },
    {
        "page_type": "components",
        "components": [
            {"type": "text", "content": "SOLAR", "position": [32, 2], "align": "center", "font": "pico_8", "color": "gray"},
            {"type": "text", "content": "{{ states('sensor.solaredge_i1_ac_power')|int }}", "position": [32, 14], "align": "center", "font": "eleven_pix", "color": "yellow"},
            {"type": "text", "content": "W", "position": [32, 28], "align": "center", "font": "pico_8", "color": "yellow"},
            {"type": "text", "content": "TODAY {{ states('sensor.energy_production_today')|round(1) }} KWH", "position": [32, 56], "align": "center", "font": "pico_8", "color": "white"},
        ],
    },
    {
        "page_type": "components",
        "variables": {
            "net": (
                "{{ ((states('sensor.energyhome_electrical_power_from_grid')|float"
                " - states('sensor.energyhome_electrical_power_to_grid')|float)|abs"
                " / 1000)|round(2) }}"
            ),
        },
        "components": [
            {"type": "text", "content": "GRID POWER", "position": [32, 2], "align": "center", "font": "pico_8", "color": "gray"},
            {"type": "text", "content": "{{ net }}", "position": [32, 14], "align": "center", "font": "eleven_pix", "color": "blue"},
            {"type": "text", "content": "KW", "position": [32, 28], "align": "center", "font": "pico_8", "color": "gray"},
            {"type": "text", "content": "MONTH {{ states('sensor.energy_monthly')|round(0) }} KWH", "position": [32, 56], "align": "center", "font": "pico_8", "color": "white"},
        ],
    },
    {
        "page_type": "components",
        "components": [
            {"type": "text", "content": "CLIMATE", "position": [32, 2], "align": "center", "font": "pico_8", "color": "gray"},
            {"type": "text", "content": "IN {{ states('" + _NETATMO + "_temperatuur')|round(1) }}C", "position": [32, 12], "align": "center", "font": "gicko", "color": "white"},
            {"type": "text", "content": "{{ states('" + _NETATMO + "_luchtvochtigheid')|int }}% RH", "position": [32, 22], "align": "center", "font": "pico_8", "color": "gray"},
            {"type": "rectangle", "position": [8, 33], "size": [48, 1], "color": [60, 60, 60], "filled": True},
            {"type": "text", "content": "OUT {{ states('" + _OUT + "')|round(1) }}C", "position": [32, 39], "align": "center", "font": "gicko", "color": "blue"},
            {"type": "text", "content": "CO2 {{ states('" + _NETATMO + "_kooldioxide')|int }} PPM", "position": [32, 56], "align": "center", "font": "pico_8", "color": "gray"},
        ],
    },
    {
        "page_type": "components",
        "components": [
            {"type": "text", "content": "WEATHER", "position": [32, 2], "align": "center", "font": "pico_8", "color": "gray"},
            {"type": "text", "content": "{{ states('weather.forecast_thuis_boom')|replace('-',' ') }}", "position": [32, 18], "align": "center", "font": "five_pix", "color": "cyan"},
            {"type": "text", "content": "{{ states('" + _OUT + "')|round(1) }}C", "position": [32, 38], "align": "center", "font": "eleven_pix", "color": "white"},
        ],
    },
]
