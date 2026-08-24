"""Read the Home Assistant energy configuration and reuse it here.

The user already told Home Assistant which sensors carry the grid, solar,
battery, gas and water figures. Reading that configuration back means the
energy screens need no separate setup: pick the mode and the screens fill
themselves.

`homeassistant.components.energy.data` is an internal API with no stability
promise, so every read is defensive and a failure degrades to "nothing
discovered" rather than raising.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
import math
from typing import Any

from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .units import as_float

_LOGGER = logging.getLogger(__name__)

TOTALS_CACHE_SECONDS = 300


@dataclass(slots=True)
class EnergySources:
    """Entity and statistic ids discovered from the HA energy configuration.

    Fields ending in ``_power`` hold entity ids reporting watts right now.
    Fields ending in ``_stat`` hold statistic ids, which may be an entity id
    or an external id such as ``nhc2:...gasvolume``, so never assume a dot.
    """

    price_now: str | None = None
    price_forecast: str | None = None
    grid_import_power: str | None = None
    grid_export_power: str | None = None
    grid_net_power: str | None = None
    grid_import_stat: str | None = None
    grid_export_stat: str | None = None
    solar_power: str | None = None
    solar_stat: str | None = None
    solar_forecast_entries: list[str] = field(default_factory=list)
    battery_soc: str | None = None
    battery_power: str | None = None
    battery_in_stat: str | None = None
    battery_out_stat: str | None = None
    gas_stat: str | None = None
    water_stats: list[str] = field(default_factory=list)

    @property
    def has_electricity(self) -> bool:
        return bool(self.grid_import_power or self.grid_net_power or self.solar_power)

    @property
    def has_battery(self) -> bool:
        return bool(self.battery_soc or self.battery_power)

    @property
    def has_solar(self) -> bool:
        return bool(self.solar_power or self.solar_stat)


def _clean(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _grid_flows(source: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Return a grid source's flows for either config schema.

    Older Home Assistant nests grid flows under ``flow_from``/``flow_to``;
    newer versions put a single flow directly on the source.
    """
    flows = source.get(key)
    if isinstance(flows, list):
        return [flow for flow in flows if isinstance(flow, dict)]
    return [source]


def parse_sources(preferences: dict[str, Any]) -> EnergySources:
    """Turn an energy preferences payload into an ``EnergySources``."""
    found = EnergySources()
    for source in preferences.get("energy_sources") or []:
        if not isinstance(source, dict):
            continue
        kind = str(source.get("type", ""))
        power = source.get("power_config") or {}
        if kind == "solar":
            found.solar_stat = _clean(source.get("stat_energy_from")) or found.solar_stat
            found.solar_power = (
                _clean(source.get("stat_rate")) or _clean(power.get("stat_rate")) or found.solar_power
            )
            # The energy config already records which config entries produce a
            # solar forecast, so read the goal source from there rather than
            # guessing it from a platform name. The key can be None or absent.
            forecast = source.get("config_entry_solar_forecast")
            if isinstance(forecast, list):
                for entry in forecast:
                    if entry_id := _clean(entry):
                        found.solar_forecast_entries.append(entry_id)
        elif kind == "battery":
            found.battery_soc = _clean(source.get("stat_soc")) or found.battery_soc
            found.battery_power = (
                _clean(source.get("stat_rate"))
                or _clean(power.get("stat_rate"))
                or found.battery_power
            )
            found.battery_out_stat = _clean(source.get("stat_energy_from")) or found.battery_out_stat
            found.battery_in_stat = _clean(source.get("stat_energy_to")) or found.battery_in_stat
        elif kind == "gas":
            found.gas_stat = _clean(source.get("stat_energy_from")) or found.gas_stat
        elif kind == "water":
            if stat := _clean(source.get("stat_energy_from")):
                found.water_stats.append(stat)
        elif kind == "grid":
            found.grid_net_power = _clean(source.get("stat_rate")) or found.grid_net_power
            found.grid_import_power = (
                _clean(power.get("stat_rate_from")) or found.grid_import_power
            )
            found.grid_export_power = _clean(power.get("stat_rate_to")) or found.grid_export_power
            for flow in _grid_flows(source, "flow_from"):
                found.grid_import_stat = (
                    _clean(flow.get("stat_energy_from")) or found.grid_import_stat
                )
                found.price_now = _clean(flow.get("entity_energy_price")) or found.price_now
                flow_power = flow.get("power_config") or {}
                found.grid_import_power = (
                    _clean(flow_power.get("stat_rate_from"))
                    or _clean(flow_power.get("stat_rate"))
                    or found.grid_import_power
                )
            for flow in _grid_flows(source, "flow_to"):
                found.grid_export_stat = _clean(flow.get("stat_energy_to")) or found.grid_export_stat
                flow_power = flow.get("power_config") or {}
                found.grid_export_power = (
                    _clean(flow_power.get("stat_rate_to"))
                    or _clean(flow_power.get("stat_rate"))
                    or found.grid_export_power
                )

    for device in preferences.get("device_consumption_water") or []:
        if isinstance(device, dict) and (stat := _clean(device.get("stat_consumption"))):
            found.water_stats.append(stat)
    return found


def find_price_forecast(hass: HomeAssistant, price_entity: str | None) -> str | None:
    """Find a sensor holding an hourly price curve in its attributes.

    Day-ahead integrations publish tomorrow's prices as a ``prices`` list of
    ``{"time": ..., "price": ...}`` mappings on a sibling of the current-price
    sensor. Prefer the sibling sharing the longest name prefix with the
    configured price entity, so multi-provider setups stay apart.
    """
    candidates: list[tuple[int, str]] = []
    for state in hass.states.async_all("sensor"):
        prices = state.attributes.get("prices") or state.attributes.get("prices_today")
        if not isinstance(prices, list) or len(prices) < 2:
            continue
        first = prices[0]
        if not isinstance(first, dict) or as_float(first.get("price")) is None:
            continue
        score = 0
        if price_entity:
            for a, b in zip(price_entity, state.entity_id, strict=False):
                if a != b:
                    break
                score += 1
        candidates.append((score, state.entity_id))
    if not candidates:
        return None
    return max(candidates)[1]


async def async_discover(hass: HomeAssistant) -> EnergySources:
    """Read the energy dashboard configuration, or return empty sources."""
    try:
        from homeassistant.components.energy.data import async_get_manager

        manager = await async_get_manager(hass)
        preferences = manager.data
    except Exception as err:  # noqa: BLE001 - internal API, never fail setup over it
        _LOGGER.debug("Energy configuration unavailable: %s", err)
        return EnergySources()
    if not preferences:
        _LOGGER.debug("No energy dashboard configuration to discover from")
        return EnergySources()
    found = parse_sources(dict(preferences))
    found.price_forecast = find_price_forecast(hass, found.price_now)
    return found


def house_power_template(found: EnergySources, *, battery_discharge_positive: bool = True) -> str:
    """A Jinja expression for the house load in watts.

    House load is what the grid delivers, plus what the panels make, plus what
    the battery gives back, minus whatever leaves the house. Home Assistant
    treats a battery rate as positive while discharging; set
    ``battery_discharge_positive`` to False for an inverted sensor.
    """
    terms: list[str] = []
    if found.grid_import_power and found.grid_export_power:
        terms.append(f"states('{found.grid_import_power}')|float(0)")
        terms.append(f"- states('{found.grid_export_power}')|float(0)")
    elif found.grid_net_power:
        terms.append(f"states('{found.grid_net_power}')|float(0)")
    if found.solar_power:
        terms.append(f"+ states('{found.solar_power}')|float(0)")
    if found.battery_power:
        sign = "+" if battery_discharge_positive else "-"
        terms.append(f"{sign} states('{found.battery_power}')|float(0)")
    if not terms:
        return "{{ 0 }}"
    expression = " ".join(terms).lstrip("+ ")
    return f"{{{{ ({expression}) | round(0) }}}}"


async def _async_hourly_change_rows(
    hass: HomeAssistant, statistic_ids: list[str]
) -> dict[str, list[tuple[datetime | None, float]]]:
    """Read each statistic's per-hour change since local midnight, cached.

    The daily total and the hourly history graph both want the same recorder
    read: today's change per hour, local midnight until now. Keep that read in
    one place so they issue one query and share one cache rather than each
    hitting the recorder on its own clock.

    Energy statistics come back in kilowatt hours whatever the sensor reports,
    because the panels label every energy figure ``kWh``. Without that the
    recorder returns the sensor's own unit and a meter reporting watt hours
    reads a thousand times too high. Other unit classes, such as the volume
    behind a gas or water meter, keep the unit the sensor uses.

    A statistic the recorder has no rows for is left out of the result, so a
    caller can tell "no data" apart from "zero used today".
    """
    wanted = {stat for stat in statistic_ids if stat}
    if not wanted:
        return {}

    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.statistics import statistics_during_period

    now = dt_util.utcnow()
    cache: dict[str, Any] = hass.data.setdefault("divoom_times_gate_energy_totals", {})
    cached_at = cache.get("at")
    if (
        cached_at is not None
        and now - cached_at < timedelta(seconds=TOTALS_CACHE_SECONDS)
        and wanted <= set(cache.get("values", {}))
    ):
        return {stat: cache["values"][stat] for stat in wanted}

    start = dt_util.start_of_local_day()
    rows = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        now,
        wanted,
        "hour",
        {"energy": UnitOfEnergy.KILO_WATT_HOUR},
        {"change"},
    )
    series: dict[str, list[tuple[datetime | None, float]]] = {}
    for stat, entries in rows.items():
        points: list[tuple[datetime | None, float]] = []
        for entry in entries:
            if (value := as_float(entry.get("change"))) is None:
                continue
            when = entry.get("start")
            stamp = dt_util.utc_from_timestamp(float(when)) if when is not None else None
            points.append((stamp, value))
        series[stat] = points
    cache["at"] = now
    cache["values"] = {**cache.get("values", {}), **series}
    return {stat: series[stat] for stat in wanted if stat in series}


async def async_daily_totals(
    hass: HomeAssistant, statistic_ids: list[str]
) -> dict[str, float]:
    """Sum today's change for each statistic id, local midnight until now.

    This reads the same long-term statistics the energy dashboard reads, so
    the totals on the panel match the totals on the dashboard. Results are
    cached briefly because a daily total barely moves between refresh ticks.
    """
    rows = await _async_hourly_change_rows(hass, statistic_ids)
    return {stat: sum(value for _, value in points) for stat, points in rows.items()}


HISTORY_HOURS = 24


async def async_hourly_changes(
    hass: HomeAssistant, statistic_ids: list[str]
) -> dict[str, list[float | None]]:
    """Today's change per hour for each statistic id, one slot per local hour.

    Each result is a 24-slot list indexed by hour of the local day. An hour
    that has already begun reads its change (zero when nothing moved); an hour
    that has not happened yet stays ``None`` so the graph leaves it empty rather
    than drawing a zero. Shares the recorder read and cache with
    ``async_daily_totals`` through ``_async_hourly_change_rows``.
    """
    rows = await _async_hourly_change_rows(hass, statistic_ids)
    now_local = dt_util.now()
    current_hour = now_local.hour
    result: dict[str, list[float | None]] = {}
    for stat in statistic_ids:
        if not stat:
            continue
        # Every hour up to and including the current one has elapsed, so start
        # them at zero; leave the rest of the day empty.
        slots: list[float | None] = [
            0.0 if hour <= current_hour else None for hour in range(HISTORY_HOURS)
        ]
        for stamp, value in rows.get(stat, []):
            if stamp is None:
                continue
            local = dt_util.as_local(stamp)
            if local.date() != now_local.date():
                continue
            hour = local.hour
            if 0 <= hour < HISTORY_HOURS:
                slots[hour] = (slots[hour] or 0.0) + value
        result[stat] = slots
    return result


async def async_day_curve(hass: HomeAssistant, statistic_id: str) -> list[float]:
    """Hourly means since local midnight, for the curve behind a panel.

    The solar panel draws the day's shape behind its headline figure. That is
    artwork, so it may only move when the hour turns; caching it on the same
    clock as the daily totals keeps the background from being re-sent on every
    refresh tick.
    """
    if not statistic_id:
        return []

    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.statistics import statistics_during_period

    now = dt_util.utcnow()
    cache: dict[str, Any] = hass.data.setdefault("divoom_times_gate_energy_curves", {})
    cached = cache.get(statistic_id)
    if cached is not None and now - cached["at"] < timedelta(seconds=TOTALS_CACHE_SECONDS):
        values: list[float] = cached["values"]
        return values

    start = dt_util.start_of_local_day()
    rows = await get_instance(hass).async_add_executor_job(
        statistics_during_period, hass, start, now, {statistic_id}, "hour", None, {"mean"}
    )
    curve = [
        value
        for entry in rows.get(statistic_id, [])
        if (value := as_float(entry.get("mean"))) is not None
    ]
    cache[statistic_id] = {"at": now, "values": curve}
    return curve


POWER_RANGE_DAYS = 7
# A symmetric fallback span so the bar has a real range when the recorder gives
# nothing. The exact number is unit-blind (the sensor may report W or kW), so it
# only needs to be non-zero: the zero marker still lands at centre and a value
# only barely moves the fill, which is the honest reading for "range unknown".
_POWER_RANGE_FALLBACK = 1000.0


def _tidy_step(magnitude: float) -> float:
    """A rounding step that keeps the bar's ends tidy at the value's scale.

    A range in watts wants rounding to hundreds; the same code in kilowatts
    wants tenths. Pick the step from the larger end so both ends round to the
    same grid.
    """
    if magnitude >= 1000:
        return 100.0
    if magnitude >= 100:
        return 10.0
    if magnitude >= 10:
        return 1.0
    return 0.1


def round_power_range(lo: float, hi: float) -> tuple[float, float]:
    """Round a charging/discharging range outward to tidy ends.

    Rounding outward never clips a real reading off the end of the bar, and a
    tidy end keeps the zero marker landing on a predictable band.
    """
    step = _tidy_step(max(abs(lo), abs(hi)))
    low = math.floor(lo / step) * step
    high = math.ceil(hi / step) * step
    if high <= low:  # a flat sensor, or a single sample: keep a non-zero span
        high = low + step
    return low, high


async def async_power_range(
    hass: HomeAssistant, statistic_id: str, current: float | None = None
) -> tuple[float, float]:
    """Charging/discharging bounds for a battery power bar, last seven days.

    The bipolar bar needs a minimum (charging, negative) and a maximum
    (discharging, positive) to place its zero point. Reading them from
    long-term statistics means the user never configures them, and reading the
    seven-day min/max keeps a single spike from squashing the everyday range.

    Cached on the same clock as the daily totals so the bounds do not re-read
    the recorder on every refresh tick. Falls back to a symmetric range around
    the current value, then to a default span, so the caller never divides by
    zero.
    """
    fallback_span = abs(current) if current else _POWER_RANGE_FALLBACK
    fallback = (-fallback_span, fallback_span)
    if not statistic_id:
        return fallback

    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.statistics import statistics_during_period

    now = dt_util.utcnow()
    cache: dict[str, Any] = hass.data.setdefault("divoom_times_gate_energy_power_range", {})
    cached = cache.get(statistic_id)
    if cached is not None and now - cached["at"] < timedelta(seconds=TOTALS_CACHE_SECONDS):
        bounds: tuple[float, float] = cached["values"]
        return bounds

    start = now - timedelta(days=POWER_RANGE_DAYS)
    try:
        rows = await get_instance(hass).async_add_executor_job(
            statistics_during_period,
            hass,
            start,
            now,
            {statistic_id},
            "day",
            None,
            {"min", "max"},
        )
    except Exception as err:  # noqa: BLE001 - recorder may be absent
        _LOGGER.debug("energy power range unavailable: %s", err)
        return fallback

    lows = [v for e in rows.get(statistic_id, []) if (v := as_float(e.get("min"))) is not None]
    highs = [v for e in rows.get(statistic_id, []) if (v := as_float(e.get("max"))) is not None]
    if not lows or not highs:
        return fallback
    result = round_power_range(min(lows), max(highs))
    cache[statistic_id] = {"at": now, "values": result}
    return result
