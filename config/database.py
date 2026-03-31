# ─────────────────────────────────────────────────────────────
# config/database.py — in-memory store, all state lives here
# ─────────────────────────────────────────────────────────────
from datetime import datetime, timedelta
from config.settings import TIER_FREE, STATUS_ACTIVE, RENEWAL_WARNING_DAYS

USERS: dict[int, dict] = {}
SELLER_CLIENTS: dict[int, dict] = {}
SIGNAL_HISTORY: dict[int, list] = {}

# ── Trade results per seller ──────────────────────────────────
# { user_id: [ {"pair", "direction", "outcome": "tp"|"sl",
#               "entry", "close_price", "time": datetime} ] }
TRADE_RESULTS: dict[int, list] = {}

# ─── Users ────────────────────────────────────────────────────

def get_or_create_user(user_id: int, username: str = "") -> dict:
    if user_id not in USERS:
        USERS[user_id] = {
            "tier": TIER_FREE, "balance": 0.0, "risk_pct": 1.0,
            "mode": None, "username": username, "joined": datetime.now(),
        }
    return USERS[user_id]

def set_user_mode(user_id: int, mode: str):
    if user_id in USERS: USERS[user_id]["mode"] = mode

def set_user_account(user_id: int, balance: float, risk_pct: float):
    if user_id in USERS:
        USERS[user_id]["balance"] = balance
        USERS[user_id]["risk_pct"] = risk_pct

def get_user_tier(user_id: int) -> str:
    return USERS.get(user_id, {}).get("tier", TIER_FREE)

def set_user_tier(user_id: int, tier: str):
    if user_id in USERS: USERS[user_id]["tier"] = tier

def is_pro(user_id: int) -> bool:
    from config.settings import TIER_PRO, TIER_LIFETIME
    return get_user_tier(user_id) in (TIER_PRO, TIER_LIFETIME)

# ─── Seller clients ───────────────────────────────────────────

def register_seller(user_id: int, username: str) -> dict:
    if user_id not in SELLER_CLIENTS:
        SELLER_CLIENTS[user_id] = {
            "status": STATUS_ACTIVE, "username": username, "channel": "",
            "expires": datetime.now() + timedelta(days=30),
            "vip_link": "", "signal_count": 0, "activated": datetime.now(),
        }
    else:
        SELLER_CLIENTS[user_id]["status"] = STATUS_ACTIVE
        SELLER_CLIENTS[user_id]["expires"] = datetime.now() + timedelta(days=30)
    return SELLER_CLIENTS[user_id]

def suspend_seller(user_id: int):
    if user_id in SELLER_CLIENTS: SELLER_CLIENTS[user_id]["status"] = "suspended"

def get_seller(user_id: int) -> dict | None:
    return SELLER_CLIENTS.get(user_id)

def is_seller_active(user_id: int) -> bool:
    c = SELLER_CLIENTS.get(user_id)
    if not c: return False
    if c["status"] != STATUS_ACTIVE: return False
    if c.get("expires") and datetime.now() > c["expires"]:
        c["status"] = "suspended"; return False
    return True

def set_seller_channel(user_id: int, channel: str):
    if user_id in SELLER_CLIENTS: SELLER_CLIENTS[user_id]["channel"] = channel

def set_seller_vip_link(user_id: int, link: str):
    if user_id in SELLER_CLIENTS: SELLER_CLIENTS[user_id]["vip_link"] = link

def add_signal_to_history(user_id: int, signal: dict):
    if user_id not in SIGNAL_HISTORY: SIGNAL_HISTORY[user_id] = []
    SIGNAL_HISTORY[user_id].insert(0, signal)
    SIGNAL_HISTORY[user_id] = SIGNAL_HISTORY[user_id][:5]

def get_signal_history(user_id: int) -> list:
    return SIGNAL_HISTORY.get(user_id, [])

def get_sellers_expiring_soon() -> list[int]:
    cutoff = datetime.now() + timedelta(days=RENEWAL_WARNING_DAYS)
    return [uid for uid, c in SELLER_CLIENTS.items()
            if c["status"] == STATUS_ACTIVE and c.get("expires") and c["expires"] <= cutoff]

def get_all_active_sellers() -> list[int]:
    return [uid for uid, c in SELLER_CLIENTS.items() if c["status"] == STATUS_ACTIVE]

# ─── Trade results ────────────────────────────────────────────

def record_trade_result(user_id: int, pair: str, direction: str,
                        outcome: str, entry: float, close_price: float):
    """outcome must be 'tp' or 'sl'"""
    if user_id not in TRADE_RESULTS: TRADE_RESULTS[user_id] = []
    TRADE_RESULTS[user_id].insert(0, {
        "pair": pair, "direction": direction, "outcome": outcome,
        "entry": entry, "close_price": close_price, "time": datetime.now(),
    })
    # Keep last 200 trades max
    TRADE_RESULTS[user_id] = TRADE_RESULTS[user_id][:200]

def get_results_summary(user_id: int) -> dict:
    """Returns wins/losses for this week, this month, and all time."""
    now = datetime.now()
    week_start  = now - timedelta(days=now.weekday())         # Monday
    month_start = now.replace(day=1, hour=0, minute=0, second=0)

    all_results = TRADE_RESULTS.get(user_id, [])

    def _count(results):
        wins = sum(1 for r in results if r["outcome"] == "tp")
        losses = sum(1 for r in results if r["outcome"] == "sl")
        return wins, losses

    week_trades  = [r for r in all_results if r["time"] >= week_start.replace(hour=0, minute=0, second=0)]
    month_trades = [r for r in all_results if r["time"] >= month_start]

    ww, wl = _count(week_trades)
    mw, ml = _count(month_trades)
    aw, al = _count(all_results)

    total_week  = ww + wl
    total_month = mw + ml
    total_all   = aw + al

    return {
        "week":  {"wins": ww, "losses": wl, "total": total_week,
                  "rate": round(ww/total_week*100) if total_week else 0},
        "month": {"wins": mw, "losses": ml, "total": total_month,
                  "rate": round(mw/total_month*100) if total_month else 0},
        "all":   {"wins": aw, "losses": al, "total": total_all,
                  "rate": round(aw/total_all*100) if total_all else 0},
        "recent": all_results[:5],
    }
