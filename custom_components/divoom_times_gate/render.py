"""Render the 5 Times Gate screens as 128x128 JPEG images from HA state.

POC: the five screens (battery / solar / grid / climate / weather) and their
entity ids are hard-coded to the author's setup. A later iteration will make
screens + components configurable from the UI (Jinja2 templated, like
gickowtf/pixoo-homeassistant which this borrows ideas from).
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from homeassistant.core import HomeAssistant

from .const import SCREEN_SIZE as S

# Pillow >=10.1 returns a scalable TrueType DejaVu font from load_default(size),
# so we don't need to bundle a font file.
_FONT_CACHE: dict[int, ImageFont.FreeTypeFont] = {}


def _font(size: int) -> ImageFont.FreeTypeFont:
    if size not in _FONT_CACHE:
        try:
            _FONT_CACHE[size] = ImageFont.load_default(size)
        except TypeError:  # very old Pillow without size arg
            _FONT_CACHE[size] = ImageFont.load_default()
    return _FONT_CACHE[size]


def _state(hass: HomeAssistant, entity_id: str) -> str | None:
    st = hass.states.get(entity_id)
    if st is None or st.state in ("unknown", "unavailable", None):
        return None
    return st.state


def _num(hass: HomeAssistant, entity_id: str, default: float = 0.0) -> float:
    v = _state(hass, entity_id)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _ctext(d: ImageDraw.ImageDraw, cx: int, y: int, text: str, size: int, fill) -> None:
    f = _font(size)
    bbox = d.textbbox((0, 0), text, font=f)
    d.text((cx - (bbox[2] - bbox[0]) / 2, y), text, font=f, fill=fill)


def _canvas(border) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (S, S), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([2, 2, S - 3, S - 3], outline=border, width=3)
    return img, d


def _to_jpeg(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, "JPEG", quality=95)
    return buf.getvalue()


# --- the five screens -------------------------------------------------------

def render_home_battery(hass: HomeAssistant) -> bytes:
    soc = _num(hass, "sensor.hame_energy_hmg_50_acd929a74998_battery_state_of_charge")
    status = (_state(hass, "sensor.hame_energy_hmg_50_acd929a74998_battery_working_status") or "").lower()
    power = int(_num(hass, "sensor.hame_energy_hmg_50_acd929a74998_combined_power"))
    cap = _num(hass, "sensor.hame_energy_hmg_50_acd929a74998_battery_capacity")

    color = (0, 255, 0)
    if soc < 20:
        color = (255, 0, 0)
    elif soc < 50:
        color = (255, 140, 0)
    elif status == "charging":
        color = (250, 204, 21)

    img, d = _canvas(color)
    _ctext(d, S // 2, 8, "HOME BATTERY", 13, (170, 170, 170))
    _ctext(d, S // 2, 30, f"{round(soc)}%", 46, color)
    bar_w, bar_x, bar_y, bar_h = 88, 20, 84, 12
    d.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], outline=(85, 85, 85))
    d.rectangle([bar_x + 1, bar_y + 1, bar_x + 1 + int((bar_w - 2) * soc / 100), bar_y + bar_h - 1], fill=color)
    arrow = "+" if status == "charging" else "-" if status == "discharging" else "="
    _ctext(d, S // 2, 102, f"{arrow}{abs(power)}W  {cap:.1f}kWh", 13, (255, 255, 255))
    return _to_jpeg(img)


def render_solar(hass: HomeAssistant) -> bytes:
    power = int(_num(hass, "sensor.solaredge_i1_ac_power"))
    today = _num(hass, "sensor.energy_production_today")
    tomorrow = _num(hass, "sensor.energy_production_tomorrow")
    producing = power > 10
    color = (250, 204, 21) if producing else (90, 90, 90)

    img, d = _canvas(color)
    _ctext(d, S // 2, 8, "SOLAR", 13, (170, 170, 170))
    _ctext(d, S // 2, 34, f"{power} W" if producing else "NO SUN", 28 if producing else 20, color)
    _ctext(d, S // 2, 76, f"Today: {today:.1f} kWh", 14, (255, 255, 255))
    _ctext(d, S // 2, 100, f"Tomorrow: {tomorrow:.1f} kWh", 12, (170, 170, 170))
    return _to_jpeg(img)


def render_grid_power(hass: HomeAssistant) -> bytes:
    from_grid = _num(hass, "sensor.energyhome_electrical_power_from_grid")
    to_grid = _num(hass, "sensor.energyhome_electrical_power_to_grid")
    net = from_grid - to_grid
    monthly = _num(hass, "sensor.energy_monthly")
    exporting = net < 0
    color = (0, 255, 0) if exporting else (255, 0, 0) if abs(net) > 2000 else (96, 165, 250)

    img, d = _canvas(color)
    _ctext(d, S // 2, 8, "GRID POWER", 13, (170, 170, 170))
    _ctext(d, S // 2, 30, f"{abs(net) / 1000:.2f}", 44, color)
    _ctext(d, S // 2, 76, "-> EXPORT" if exporting else "<- IMPORT", 13, (170, 170, 170))
    _ctext(d, S // 2, 100, f"Month: {monthly:.0f} kWh", 13, (255, 255, 255))
    return _to_jpeg(img)


def render_climate(hass: HomeAssistant) -> bytes:
    indoor = _num(hass, "sensor.netatmo_weather_station_temperatuur")
    outdoor = _num(hass, "sensor.netatmo_weather_station_netatmo_outdoor_module_temperatuur")
    indoor_h = int(_num(hass, "sensor.netatmo_weather_station_luchtvochtigheid"))
    co2 = int(_num(hass, "sensor.netatmo_weather_station_kooldioxide"))
    co2_color = (255, 140, 0) if co2 > 1000 else (250, 204, 21) if co2 > 800 else (0, 255, 0)

    img, d = _canvas((96, 165, 250))
    _ctext(d, S // 2, 6, "CLIMATE", 13, (170, 170, 170))
    _ctext(d, S // 2, 24, f"IN {indoor:.1f}C", 22, (255, 255, 255))
    _ctext(d, S // 2, 52, f"{indoor_h}% RH", 13, (170, 170, 170))
    d.line([16, 74, S - 16, 74], fill=(51, 51, 51))
    _ctext(d, S // 2, 80, f"OUT {outdoor:.1f}C", 22, (96, 165, 250))
    _ctext(d, S // 2, 108, f"CO2 {co2} ppm", 12, co2_color)
    return _to_jpeg(img)


_WEATHER_COLORS = {
    "sunny": (250, 204, 21), "clear-night": (96, 165, 250), "partlycloudy": (147, 197, 253),
    "cloudy": (156, 163, 175), "rainy": (59, 130, 246), "snowy": (224, 242, 254),
    "fog": (209, 213, 219), "windy": (110, 231, 183),
}


def render_weather(hass: HomeAssistant) -> bytes:
    cond = _state(hass, "weather.forecast_thuis_boom") or "unknown"
    temp = _num(hass, "sensor.netatmo_weather_station_netatmo_outdoor_module_temperatuur")
    hum = int(_num(hass, "sensor.netatmo_weather_station_netatmo_outdoor_module_luchtvochtigheid"))
    pressure = int(_num(hass, "sensor.netatmo_weather_station_atmosferische_druk"))
    color = _WEATHER_COLORS.get(cond, (255, 255, 255))

    img, d = _canvas(color)
    _ctext(d, S // 2, 8, "WEATHER", 13, (170, 170, 170))
    _ctext(d, S // 2, 34, cond.upper().replace("-", " "), 16, color)
    _ctext(d, S // 2, 66, f"{temp:.1f}C", 26, (255, 255, 255))
    _ctext(d, S // 2, 104, f"{hum}% RH  {pressure} hPa", 12, (170, 170, 170))
    return _to_jpeg(img)


# screen index -> renderer
SCREEN_RENDERERS = {
    0: render_home_battery,
    1: render_solar,
    2: render_grid_power,
    3: render_climate,
    4: render_weather,
}
