"""Number formatting for the 128x128 panel.

Values are shown on a small screen, so every formatter trades precision for
width: power switches to kW above 1000 W, energy keeps one decimal, and a
price keeps three because day-ahead electricity prices live between -0.01 and
0.30 EUR/kWh.
"""
from __future__ import annotations


def as_float(value: object, default: float | None = None) -> float | None:
    """Parse a state string into a float, or return ``default``."""
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def format_power(watts: float, *, signed: bool = False) -> str:
    """Format watts, switching to kW above 1000 W.

    ``signed`` prefixes a positive value with ``+`` so import and export read
    differently at a glance.
    """
    sign = "+" if signed and watts > 0 else ""
    magnitude = abs(watts)
    if magnitude >= 1000:
        return f"{sign}{watts / 1000:.1f}kW"
    return f"{sign}{watts:.0f}W"


def format_energy(kwh: float) -> str:
    """Format kilowatt-hours: one decimal, or none once past 100 kWh."""
    if abs(kwh) >= 100:
        return f"{kwh:.0f}kWh"
    return f"{kwh:.1f}kWh"


def format_price(price: float, currency: str = "") -> str:
    """Format an energy price with three decimals, e.g. ``0.184``."""
    return f"{price:.3f}{currency}"


def format_percent(value: float) -> str:
    return f"{value:.0f}%"


def format_volume(value: float, unit: str) -> str:
    """Format a gas or water reading, keeping the source unit."""
    if abs(value) >= 100:
        return f"{value:.0f}{unit}"
    return f"{value:.1f}{unit}"


def format_auto(value: float, unit: str | None) -> str:
    """Format ``value`` using the formatter that matches ``unit``."""
    normalized = (unit or "").strip()
    lowered = normalized.lower()
    if lowered == "w":
        return format_power(value)
    if lowered == "kw":
        return format_power(value * 1000)
    if lowered in ("kwh", "wh"):
        return format_energy(value if lowered == "kwh" else value / 1000)
    if lowered == "%":
        return format_percent(value)
    if "/kwh" in lowered:
        return format_price(value)
    if not normalized:
        return f"{value:g}"
    return f"{value:g}{normalized}"
