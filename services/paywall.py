# ─────────────────────────────────────────────────────────────
# services/paywall.py
# Checks user tier and seller status before features run.
# ─────────────────────────────────────────────────────────────
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from config.database import is_pro, is_seller_active
from config.settings import PRO_FEATURES


UPGRADE_MESSAGE = (
    "🔒 *This is a Pro feature.*\n\n"
    "Upgrade to unlock:\n"
    "→ Live daily signals with lot size calculated for your account\n"
    "→ 7:05am automated morning signal\n"
    "→ Post signals directly to your Telegram channel\n"
    "→ Signal history\n\n"
    "📌 *Plans:*\n"
    "• Pro — $15/month\n"
    "• Lifetime — $79 one-time\n\n"
    "DM @yourusername to upgrade."
)

SUSPENDED_MESSAGE = (
    "⏸️ *Your Signal Automation System has been paused.*\n\n"
    "This usually means your subscription has expired or payment wasn't received.\n\n"
    "To reactivate, DM @yourusername and we'll sort it out immediately."
)


async def require_pro(update: Update, context: ContextTypes.DEFAULT_TYPE,
                      feature: str) -> bool:
    """
    Call this at the start of any Pro handler.
    Returns True if user can proceed, False if blocked (and sends upgrade msg).
    """
    user_id = update.effective_user.id

    if feature in PRO_FEATURES and not is_pro(user_id):
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("Upgrade to Pro →", url="https://t.me/yourusername")
        ]])
        await update.message.reply_text(
            UPGRADE_MESSAGE, parse_mode=ParseMode.MARKDOWN, reply_markup=kb
        )
        return False
    return True


async def require_active_seller(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Call this at the start of any seller-mode handler.
    Returns True if seller is active, False if suspended/not registered.
    """
    user_id = update.effective_user.id

    if not is_seller_active(user_id):
        await update.message.reply_text(
            SUSPENDED_MESSAGE, parse_mode=ParseMode.MARKDOWN
        )
        return False
    return True
