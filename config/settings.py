# ─────────────────────────────────────────────────────────────
# config/settings.py
# ─────────────────────────────────────────────────────────────
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN       = os.getenv("BOT_TOKEN", "")
MASTER_ADMIN_ID = int(os.getenv("MASTER_ADMIN_ID", "0"))

_GOLD_API_KEY_ENV = os.getenv("GOLD_API_KEY", "")
GOLD_API_URL = "https://www.goldapi.io/api/XAU/USD"

# Runtime config — set via /setconfig in Telegram or .env
BOT_CONFIG: dict[str, str] = {
    "gold_api_key":  _GOLD_API_KEY_ENV,
    "your_username": os.getenv("YOUR_USERNAME", "yourusername"),
    "vip_link":      os.getenv("VIP_LINK", "https://t.me/yourusername"),
    "mpesa_till":    os.getenv("MPESA_TILL", ""),
}

def get_config(key: str, fallback: str = "") -> str:
    return BOT_CONFIG.get(key, fallback) or fallback

def set_config(key: str, value: str):
    BOT_CONFIG[key] = value

def get_gold_api_key() -> str:
    return get_config("gold_api_key")

TIER_FREE     = "free"
TIER_PRO      = "pro"
TIER_LIFETIME = "lifetime"

PRO_FEATURES = {
    "get_signal",
    "daily_broadcast",
    "post_signal_channel",
    "signal_history",
}

PRICING = {
    TIER_FREE:     {"label": "Free",     "price": "$0",    "desc": "Risk calculator, learn strategy, signal preview"},
    TIER_PRO:      {"label": "Pro",      "price": "$15/mo","desc": "Full signals, daily broadcast, channel posting, history"},
    TIER_LIFETIME: {"label": "Lifetime", "price": "$79",   "desc": "Everything Pro, forever. One payment."},
}

STATUS_ACTIVE    = "active"
STATUS_SUSPENDED = "suspended"
STATUS_TRIAL     = "trial"

LONDON_OPEN_HOUR_EAT    = 10
LONDON_CLOSE_HOUR_EAT   = 13
DAILY_SIGNAL_HOUR_EAT   = 7
DAILY_SIGNAL_MINUTE_EAT = 5
RENEWAL_WARNING_DAYS    = 3
