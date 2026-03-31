# ─────────────────────────────────────────────────────────────
# services/scheduler.py
# Sets up recurring jobs: daily signal broadcast + renewal checks
# ─────────────────────────────────────────────────────────────
import logging
from datetime import time, timezone, timedelta
from telegram.ext import Application
from telegram.constants import ParseMode

from config.settings import DAILY_SIGNAL_HOUR_EAT, DAILY_SIGNAL_MINUTE_EAT
from config.database import USERS, is_pro, get_all_active_sellers, get_seller
from services.signal_engine import generate_london_signal, format_signal_message
from handlers.master import check_renewals

logger = logging.getLogger(__name__)

# EAT = UTC+3
EAT = timezone(timedelta(hours=3))


async def daily_trader_signal(context):
    """
    Sends live London Breakout signal to all Pro traders at 7:05am EAT.
    Also sends a one-tap "Post to channel" button to all active sellers.
    """
    logger.info("Running daily signal broadcast...")

    sig = await generate_london_signal()
    trader_msg = format_signal_message(sig)
    seller_msg = format_signal_message(sig, for_channel=True)

    # ── Broadcast to Pro traders ──
    for user_id, user in USERS.items():
        if user.get("mode") != "trader":
            continue
        if not is_pro(user_id):
            continue
        try:
            await context.bot.send_message(
                user_id,
                f"🌅 *Good morning! Your 7:05am signal is ready.*\n\n{trader_msg}",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.warning(f"Failed to send daily signal to {user_id}: {e}")

    # ── Prompt active sellers ──
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    for seller_id in get_all_active_sellers():
        client = get_seller(seller_id)
        channel = client.get("channel", "") if client else ""
        if not channel:
            continue
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📡 Post to my channel", callback_data=f"post_confirm|{channel}"),
        ]])
        try:
            context.user_data_for_chat = {"pending_signal": seller_msg}
            await context.bot.send_message(
                seller_id,
                f"🌅 *Good morning! Today's London Breakout signal:*\n\n{seller_msg}\n\n"
                f"Tap below to post it to *{channel}* instantly 👇",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb,
            )
        except Exception as e:
            logger.warning(f"Failed to send daily prompt to seller {seller_id}: {e}")


def setup_scheduler(app: Application):
    """Register all scheduled jobs on the application's job queue."""
    job_queue = app.job_queue

    # Daily signal at 7:05am EAT
    job_queue.run_daily(
        daily_trader_signal,
        time=time(DAILY_SIGNAL_HOUR_EAT, DAILY_SIGNAL_MINUTE_EAT, tzinfo=EAT),
        days=(0, 1, 2, 3, 4),   # Monday–Friday only
        name="daily_signal",
    )

    # Renewal check every day at 8am EAT
    job_queue.run_daily(
        check_renewals,
        time=time(8, 0, tzinfo=EAT),
        name="renewal_check",
    )

    logger.info("Scheduler jobs registered: daily_signal (Mon–Fri 7:05am EAT), renewal_check (daily 8am EAT)")
