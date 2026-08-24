"""Default screen configuration.

These defaults only apply until you configure the screens yourself. They stay
neutral on purpose: they name no entity, so a fresh install shows a working
clock instead of five confident labels over sensors that do not exist on your
system. The config flow offers to fill all five screens for you, and the
options flow lets you edit each one.
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

# The face the neutral first screen shows. "Big Time" is one of the per-screen
# favorites above, so the same face is already reachable from the Screen 1
# select without adding anything.
DEFAULT_CLOCK_FACE = 152

# What an unconfigured device shows: a native clock on screen 1 and black on
# the rest. Naming an entity here would be a guess about somebody else's
# system, and a wrong guess renders as a confident label over a dead sensor.
DEFAULT_SCREENS: list[dict[str, Any]] = [
    {"page_type": "clock", "clock_id": DEFAULT_CLOCK_FACE},
    {"page_type": "off"},
    {"page_type": "off"},
    {"page_type": "off"},
    {"page_type": "off"},
]
