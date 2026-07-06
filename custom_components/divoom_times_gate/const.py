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

DEFAULT_HARDWARE = 400
DEFAULT_REFRESH_INTERVAL = 60
DEFAULT_BRIGHTNESS = 100
DEFAULT_DURATION = 15  # seconds a page shows before a screen rotates to the next

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
