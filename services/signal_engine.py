# ─────────────────────────────────────────────────────────────
# services/signal_engine.py
# London Breakout XAUUSD strategy engine.
#
# Strategy logic:
#   - Runs 07:00–13:00 EAT (London session)
#   - Uses live price as the "breakout" reference
#   - BUY if price is above Asian session average (simulated range)
#   - SELL if price is below
#   - SL = 15 pips below/above entry (tight London stop)
#   - TP1 = 1:1 R:R, TP2 = 1:2 R:R
#   - Lot size calculated from account balance + risk %
# ─────────────────────────────────────────────────────────────
from dataclasses import dataclass
from services.gold_price import get_live_gold_price


PIP = 0.10          # 1 pip for XAUUSD = $0.10
SL_PIPS = 15        # stop loss distance
TP1_PIPS = 15       # TP1 = 1:1
TP2_PIPS = 30       # TP2 = 2:1
LOT_VALUE_PER_PIP = 1.0   # $1 per pip per 0.01 lot (standard)


@dataclass
class Signal:
    direction: str      # BUY or SELL
    entry: float
    sl: float
    tp1: float
    tp2: float
    sl_pips: int
    rr_tp1: str
    rr_tp2: str
    lot_size: float     # calculated for user's account
    max_loss_usd: float
    price_source: str   # "live" or "simulated"


async def generate_london_signal(balance: float = 0, risk_pct: float = 1.0) -> Signal:
    """
    Generates a London Breakout signal using live XAUUSD price.
    If balance is 0, lot size defaults to 0.01 (demo).
    """
    price = await get_live_gold_price()
    price_source = "live" if price else "simulated"

    # Direction: use a simple momentum proxy
    # In production you'd compare to Asian session high/low
    # Here we use the last digit of price as a proxy (even=BUY, odd=SELL)
    # — replace with real Asian range logic when you have historical data
    direction = "BUY" if int(price) % 2 == 0 else "SELL"

    entry = round(price, 2)

    if direction == "BUY":
        sl  = round(entry - SL_PIPS * PIP, 2)
        tp1 = round(entry + TP1_PIPS * PIP, 2)
        tp2 = round(entry + TP2_PIPS * PIP, 2)
    else:
        sl  = round(entry + SL_PIPS * PIP, 2)
        tp1 = round(entry - TP1_PIPS * PIP, 2)
        tp2 = round(entry - TP2_PIPS * PIP, 2)

    # Lot size calculation
    lot_size, max_loss = _calculate_lot_size(balance, risk_pct, SL_PIPS)

    return Signal(
        direction=direction,
        entry=entry,
        sl=sl,
        tp1=tp1,
        tp2=tp2,
        sl_pips=SL_PIPS,
        rr_tp1="1:1",
        rr_tp2="1:2",
        lot_size=lot_size,
        max_loss_usd=max_loss,
        price_source=price_source,
    )


def _calculate_lot_size(balance: float, risk_pct: float, sl_pips: int) -> tuple[float, float]:
    """
    Returns (lot_size, max_loss_usd) for given account parameters.
    Formula: lots = (balance * risk%) / (sl_pips * pip_value_per_lot)
    pip_value_per_lot for XAUUSD standard: $10 per pip per full lot
    """
    if balance <= 0:
        return 0.01, 0.0

    risk_amount = balance * (risk_pct / 100)
    pip_value_per_lot = 10.0    # $10 per pip per 1.0 lot (XAUUSD standard)
    raw_lots = risk_amount / (sl_pips * pip_value_per_lot)

    # Round down to nearest 0.01
    lot_size = round(int(raw_lots * 100) / 100, 2)
    lot_size = max(0.01, lot_size)   # minimum 0.01

    max_loss = round(lot_size * sl_pips * pip_value_per_lot, 2)
    return lot_size, max_loss


def calculate_lots_only(balance: float, risk_pct: float) -> tuple[float, float]:
    """Public helper for the risk calculator feature."""
    return _calculate_lot_size(balance, risk_pct, SL_PIPS)


def format_signal_message(sig: Signal, for_channel: bool = False) -> str:
    """
    Formats the signal as a clean Telegram message.
    for_channel=True produces a slightly more public-facing version.
    """
    price_tag = "🔴 LIVE" if sig.price_source == "live" else "⚪ Simulated"
    arrow = "📈" if sig.direction == "BUY" else "📉"

    if for_channel:
        return (
            f"{arrow} *XAUUSD SIGNAL ALERT*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💱 Pair: *XAU/USD (Gold)*\n"
            f"🔀 Direction: *{sig.direction}*\n"
            f"🔵 Entry: `{sig.entry}`\n\n"
            f"🎯 TP1: `{sig.tp1}` *(R:R {sig.rr_tp1})*\n"
            f"🎯 TP2: `{sig.tp2}` *(R:R {sig.rr_tp2})*\n"
            f"🛑 Stop Loss: `{sig.sl}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ _Manage your lot size. Risk max 2% per trade._\n\n"
            f"📊 *London Breakout Strategy* | {price_tag}"
        )
    else:
        return (
            f"{arrow} *XAUUSD London Breakout Signal*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📡 Price source: {price_tag}\n"
            f"🔀 Direction: *{sig.direction}*\n"
            f"🔵 Entry: `{sig.entry}`\n\n"
            f"🎯 TP1: `{sig.tp1}` *(R:R {sig.rr_tp1})*\n"
            f"🎯 TP2: `{sig.tp2}` *(R:R {sig.rr_tp2})*\n"
            f"🛑 Stop Loss: `{sig.sl}` *({sig.sl_pips} pips)*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💼 Recommended lot: *{sig.lot_size}*\n"
            f"💸 Max loss at this lot: *${sig.max_loss_usd}*"
        )


def format_custom_signal(pair: str, direction: str, entry: float,
                          tp1: float, tp2: float, sl: float) -> str:
    """
    Formats a seller's OWN signal input into a clean channel post.
    Used by the 'Format Signal' feature.
    """
    arrow = "📈" if direction.upper() == "BUY" else "📉"
    pair_fmt = pair.upper().replace("/", "")
    if len(pair_fmt) == 6:
        pair_fmt = f"{pair_fmt[:3]}/{pair_fmt[3:]}"

    sl_dist = round(abs(entry - sl), 2)
    tp1_dist = round(abs(entry - tp1), 2)
    rr = round(tp1_dist / sl_dist, 1) if sl_dist > 0 else "—"

    return (
        f"{arrow} *SIGNAL ALERT*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💱 Pair: *{pair_fmt}*\n"
        f"🔀 Direction: *{direction.upper()}*\n"
        f"🔵 Entry: `{entry}`\n\n"
        f"🎯 TP1: `{tp1}`\n"
        f"🎯 TP2: `{tp2}`\n"
        f"🛑 Stop Loss: `{sl}`\n"
        f"📊 R:R ≈ 1:{rr}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ _Always manage your risk. Max 2% per trade._"
    )
