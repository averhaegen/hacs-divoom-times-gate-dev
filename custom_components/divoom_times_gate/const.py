DOMAIN = "divoom_times_gate"

CONF_IP_ADDRESS = "ip_address"
CONF_LOCAL_TOKEN = "local_token"
CONF_REFRESH_INTERVAL = "refresh_interval"
CONF_SCREENS = "screens"
CONF_FACES = "faces"
CONF_HARDWARE = "hardware"
CONF_MAC = "mac"
CONF_DEVICE_ID = "device_id"

DEFAULT_HARDWARE = 400
DEFAULT_REFRESH_INTERVAL = 60
DEFAULT_BRIGHTNESS = 100
DEFAULT_DURATION = 15  # seconds a page shows before a screen rotates to the next

SCREEN_COUNT = 5
SCREEN_SIZE = 128
SCREENS = [0, 1, 2, 3, 4]

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
