"""Constants for CAME Connect integration."""

DOMAIN = "ha_cameconnect"

# Config entry keys
CONF_CLIENT_ID = "came_client_id"
CONF_CLIENT_SECRET = "came_client_secret"
CONF_USERNAME = "came_username"
CONF_PASSWORD = "came_password"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_NAME = "device_name"

# Defaults
DEFAULT_SCAN_INTERVAL = 5  # seconds

# CAME Connect API
API_BASE_CANDIDATES = [
    "https://www.cameconnect.net/api",
    "https://app.cameconnect.net/api",
]
OAUTH_AUTH_CODE_SUFFIX = "/oauth/auth-code"
OAUTH_TOKEN_SUFFIX = "/oauth/token"
OAUTH_REDIRECT_URI = "https://www.cameconnect.net/role"

# hass.storage key for token persistence
STORAGE_KEY = "ha_cameconnect_token"
STORAGE_VERSION = 1

# Gate state values
STATE_OPEN = "open"
STATE_CLOSED = "closed"
STATE_OPENING = "opening"
STATE_CLOSING = "closing"
STATE_STOPPED = "stopped"
STATE_MOVING = "moving"
STATE_UNKNOWN = "unknown"

# Command IDs
CMD_OPEN = 2
CMD_CLOSE = 5
CMD_STOP = 129
CMD_PARTIAL_OPEN = 4
CMD_OPEN_CLOSE = 8
CMD_SEQUENTIAL = 9

# ZM3 raw state codes (CommandId=1, Data[0])
CODE_MAP = {
    16: STATE_OPEN,
    17: STATE_CLOSED,
    19: STATE_STOPPED,
    32: STATE_OPENING,
    33: STATE_CLOSING,
}
