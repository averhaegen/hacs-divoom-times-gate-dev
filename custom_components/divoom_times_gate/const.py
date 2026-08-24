DOMAIN = "divoom_times_gate"

CONF_IP_ADDRESS = "ip_address"
CONF_LOCAL_TOKEN = "local_token"
CONF_REFRESH_INTERVAL = "refresh_interval"
CONF_SCREENS = "screens"
CONF_FACES = "faces"
CONF_HARDWARE = "hardware"
CONF_MAC = "mac"
CONF_DEVICE_ID = "device_id"
CONF_DASHBOARD_BASE = "dashboard_base"  # preset position (0-4) used as overlay base
CONF_DISPDATA_SECRET = "dispdata_secret"  # URL guard for the type-23 DispData view
CONF_PRESETS = "presets"  # named screen sets the user can switch between
CONF_ACTIVE_PRESET = "active_preset"

DEFAULT_PRESET = "default"  # holds any `screens` config written before presets existed
ENERGY_PRESET = "energy"

# The five energy screens, one per device slot, in the order the builder emits
# them. The screen picker keys its checkboxes on these, and the builder blanks a
# slot whose key is left out of the selection, so the names live here rather than
# as bare strings the flow and the builder would have to keep in step by hand.
ENERGY_SCREEN_PRICE = "price"
ENERGY_SCREEN_HOUSE = "house"
ENERGY_SCREEN_SOLAR_BATTERY = "solar_battery"
ENERGY_SCREEN_PRICE_GRAPH = "price_graph"
ENERGY_SCREEN_HISTORY = "history"
ENERGY_SCREENS = (
    ENERGY_SCREEN_PRICE,
    ENERGY_SCREEN_HOUSE,
    ENERGY_SCREEN_SOLAR_BATTERY,
    ENERGY_SCREEN_PRICE_GRAPH,
    ENERGY_SCREEN_HISTORY,
)

# The energy dashboard palette, copied from the Home Assistant frontend
# (src/resources/theme/color/color.globals.ts) so the panel and the dashboard
# agree on what blue means. Note that grid import is blue and export purple,
# which is the opposite of what people usually guess.
ENERGY_COLORS = {
    "grid_import": "#488fc2",
    "grid_export": "#8353d1",
    "solar": "#ff9800",
    "non_fossil": "#0f9d58",
    "battery_out": "#4db6ac",
    "battery_in": "#f06292",
    "gas": "#8e021b",
    "water": "#00bcd4",
}

# Ink for everything on the history graph that is not an energy source: the net
# consumption line, the now marker and the zero rule. Pure white glares next to
# the muted dashboard palette on an LED panel, so these read as a light grey.
ENERGY_SOFT_INK = "#B4B4B4"

# Outcome of an authenticated probe against the device (TimesGate.check_auth).
# The device never raises, so these three markers are how the rest of the
# integration tells "no answer at all" apart from "answered, token rejected".
AUTH_OK = "ok"
AUTH_INVALID = "invalid_auth"
AUTH_UNREACHABLE = "unreachable"

DEFAULT_HARDWARE = 400
DEFAULT_REFRESH_INTERVAL = 60
DEFAULT_BRIGHTNESS = 100
DEFAULT_DURATION = 15  # seconds a page shows before a screen rotates to the next

# Device font ids passed to Draw/SendHttpItemList. See docs/API.md §4.9 for the
# ids this firmware renders. Cards keep font 4, which every page written before
# these constants existed relied on.
#
# The energy panels render every live figure in font 184 (12x14), a blocky
# numeral face whose charset is `0123456789KMLIVEOFN.`. It reads cleanly at a
# distance without a five-digit value crowding the panel, and it is one of only
# four dot-carrying fonts that honour the item's `color` rather than baking one
# in, which the panels need for their accents. No firmware font carries a `k`,
# so `kW` is baked into the artwork beside the number. Font 2 (16x16) is a full
# bitmap font and remains the fallback for text that needs letters, such as the
# graph footer.
#
# The char widths are the font's cell width from docs/FONTS_CATALOG.md. Layout
# reserves that many pixels per digit to centre a value against its unit, since
# `align: 2` does not centre on this firmware (docs/API.md §4.10).
DEFAULT_DEVICE_FONT = 4
DEFAULT_LABEL_FONT = 2
ENERGY_FONT = 160
ENERGY_LABEL_FONT = 2
ENERGY_HERO_FONT = 184
ENERGY_HERO_HEIGHT = 14
ENERGY_HERO_CHAR_WIDTH = 12
ENERGY_ROW_FONT = 184
ENERGY_ROW_HEIGHT = 14
ENERGY_ROW_CHAR_WIDTH = 12

SCREEN_COUNT = 5
SCREEN_SIZE = 128
SCREENS = [0, 1, 2, 3, 4]

# Native SendHttpItemList element types the device renders entirely on its
# own (clock/date/weather) — no TextString, no polling, zero HA involvement
# once sent. See docs/API.md §4.10 "type values" table. Shared by
# dispdata_text items pages and card headers.
NATIVE_KIND_TYPES = {
    "second": 1,
    "minute": 2,
    "hour": 3,
    "ampm": 4,  # AM/PM marker; pair with "time_short" for a 12h clock
    "time_short": 5,  # hh:mm
    "time": 6,  # hh:mm:ss
    "clock": 6,  # alias of "time"
    "year": 7,
    "day": 8,
    "month": 9,
    "mon_year": 10,
    "month_day": 11,  # eng-month.day
    "weekday_2": 13,  # SU
    "weekday_3": 14,  # SUN
    "weekday_full": 15,  # SUNDAY
    "month_3": 16,  # JAN
    "temperature": 17,
    "temp_max": 18,
    "temp_min": 19,
    "weather": 20,  # weather word
    "noise": 21,  # dB
}

# Per-screen mode (Screen N select), used when Display source = HA Dashboard.
SCREEN_MODE_CUSTOM = "Custom"
SCREEN_MODE_OFF = "Off"

# Device-level Display source modes.
DISPLAY_HA_DASHBOARD = "HA Dashboard"
DISPLAY_OFF = "Off"
# Dynamic options are labelled "Overall Display: <face>" and
# "Independent Display: <ControlN>" (built from faces + presets at runtime).
PREFIX_OVERALL = "Overall Display: "
PREFIX_INDEPENDENT = "Independent Display: "
PREFIX_FACE = "Face: "
