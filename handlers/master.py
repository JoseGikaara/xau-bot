# ─────────────────────────────────────────────────────────────
# handlers/master.py — your private control panel via Telegram
# Only MASTER_ADMIN_ID can use any of these commands
# ─────────────────────────────────────────────────────────────
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, CommandHandler, filters
from telegram.constants import ParseMode

from config.settings import (
    MASTER_ADMIN_ID, STATUS_ACTIVE, STATUS_SUSPENDED,
    get_config, set_config, BOT_CONFIG,
)
from config.database import (
    register_seller, suspend_seller, get_seller,
    SELLER_CLIENTS, get_all_active_sellers,
    get_sellers_expiring_soon, set_user_tier, get_or_create_user,
)

# Conversation state for /setconfig
_SETCONFIG_KEY, _SETCONFIG_VAL = range(2)

CONFIGURABLE_KEYS = {
    "goldkey":  ("gold_api_key",  "Gold-API.com API key"),
    "username": ("your_username", "Your Telegram username (without @)"),
    "viplink":  ("vip_link",      "VIP upgrade link"),
    "mpesa":    ("mpesa_till",    "M-Pesa Till / Paybill number"),
}


def _is_master(user_id: int) -> bool:
    return user_id == MASTER_ADMIN_ID


# ── /myconfig — show all current settings ────────────────────
async def myconfig_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_master(update.effective_user.id): return

    gold_key = get_config("gold_api_key")
    gold_display = f"`{gold_key[:6]}...{gold_key[-4:]}`" if len(gold_key) > 10 else ("_not set_" if not gold_key else f"`{gold_key}`")

    lines = [
        "⚙️ *Bot Configuration*\n━━━━━━━━━━━━━━━━━━",
        f"🔑 Gold API key: {gold_display}",
        f"👤 Your username: `{get_config('your_username')}`",
        f"🔗 VIP link: `{get_config('vip_link')}`",
        f"💵 M-Pesa Till: `{get_config('mpesa_till') or 'not set'}`",
        "\n_To change any value:_",
        "`/setconfig goldkey YOUR_KEY`",
        "`/setconfig username yourhandle`",
        "`/setconfig viplink https://t.me/...`",
        "`/setconfig mpesa 123456`",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ── /setconfig <key> <value> ──────────────────────────────────
async def setconfig_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_master(update.effective_user.id): return

    args = context.args
    if len(args) < 2:
        keys_help = "\n".join(f"  `{k}` — {v[1]}" for k, v in CONFIGURABLE_KEYS.items())
        await update.message.reply_text(
            f"Usage: `/setconfig <key> <value>`\n\nAvailable keys:\n{keys_help}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    short_key = args[0].lower()
    value = " ".join(args[1:]).strip()

    if short_key not in CONFIGURABLE_KEYS:
        await update.message.reply_text(
            f"Unknown key `{short_key}`. Valid keys: {', '.join(CONFIGURABLE_KEYS)}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    real_key, label = CONFIGURABLE_KEYS[short_key]
    set_config(real_key, value)

    # Mask API keys in confirmation
    display = f"{value[:6]}...{value[-4:]}" if short_key == "goldkey" and len(value) > 10 else value
    await update.message.reply_text(
        f"✅ *{label}* updated to:\n`{display}`\n\nTakes effect immediately — no restart needed.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /activate <user_id> [username] ───────────────────────────
async def activate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_master(update.effective_user.id): return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /activate <user_id> [username]"); return
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("First argument must be a numeric user ID."); return

    username = args[1] if len(args) > 1 else f"user_{target_id}"
    get_or_create_user(target_id, username)
    client = register_seller(target_id, username)

    your_username = get_config("your_username", "yourusername")

    await update.message.reply_text(
        f"✅ *Activated*\n"
        f"User: `{target_id}` (@{username})\n"
        f"Expires: {client['expires'].strftime('%d %b %Y')}",
        parse_mode=ParseMode.MARKDOWN,
    )
    try:
        await context.bot.send_message(
            target_id,
            f"✅ *Your Signal Automation System is now active!*\n\n"
            f"Here are your first 3 steps:\n\n"
            f"1. Add me to your signal group (make me admin)\n"
            f"2. In the group, type /mygroup to register it\n"
            f"3. In this chat, tap *🔗 Connect Channel*\n\n"
            f"Questions? DM @{your_username} 🚀",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        await update.message.reply_text("(Could not DM client — they may not have started the bot yet.)")


# ── /suspend <user_id> ────────────────────────────────────────
async def suspend_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_master(update.effective_user.id): return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /suspend <user_id>"); return
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("Provide a numeric user ID."); return

    suspend_seller(target_id)
    your_username = get_config("your_username", "yourusername")

    await update.message.reply_text(
        f"⏸️ *Suspended*\nUser `{target_id}` — all commands frozen.",
        parse_mode=ParseMode.MARKDOWN,
    )
    try:
        await context.bot.send_message(
            target_id,
            f"⏸️ *Your Signal Automation System has been paused.*\n\n"
            f"Usually due to a missed renewal.\n"
            f"DM @{your_username} to reactivate.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        pass


# ── /clients — full CRM dashboard ────────────────────────────
async def clients_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_master(update.effective_user.id): return
    if not SELLER_CLIENTS:
        await update.message.reply_text("No clients registered yet."); return

    active   = sum(1 for c in SELLER_CLIENTS.values() if c["status"] == STATUS_ACTIVE)
    suspended = len(SELLER_CLIENTS) - active

    lines = [f"👥 *Clients ({len(SELLER_CLIENTS)} total · {active} active · {suspended} paused)*\n━━━━━━━━━━━━━━━━━━"]
    for uid, c in SELLER_CLIENTS.items():
        emoji = "✅" if c["status"] == STATUS_ACTIVE else "⏸️"
        expires = c["expires"].strftime("%d %b %Y") if c.get("expires") else "N/A"
        channel = c.get("channel") or "not connected"
        lines.append(
            f"\n{emoji} *{c.get('username','?')}* (`{uid}`)\n"
            f"   Expires: {expires} · Channel: {channel}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ── /broadcast <message> ─────────────────────────────────────
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_master(update.effective_user.id): return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast Your message here"); return

    message = " ".join(context.args)
    active = get_all_active_sellers()
    sent = failed = 0
    for uid in active:
        try:
            await context.bot.send_message(
                uid,
                f"📢 *Message from your system provider:*\n\n{message}",
                parse_mode=ParseMode.MARKDOWN,
            )
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"📢 *Broadcast done*\n✅ Sent: {sent} · ❌ Failed: {failed}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /grantpro <user_id> ───────────────────────────────────────
async def grantpro_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_master(update.effective_user.id): return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /grantpro <user_id>"); return
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("Provide a numeric user ID."); return

    from config.settings import TIER_PRO
    set_user_tier(target_id, TIER_PRO)
    await update.message.reply_text(f"✅ User `{target_id}` upgraded to Pro.", parse_mode=ParseMode.MARKDOWN)
    try:
        await context.bot.send_message(
            target_id,
            "🎉 *Your account has been upgraded to Pro!*\n\n"
            "→ Live daily signals with lot size calculated\n"
            "→ 7:05am automated morning signal\n\n"
            "Type 📊 *Get Signal* to try it now.",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        pass


# ── Scheduled renewal warnings ────────────────────────────────
async def check_renewals(context):
    expiring = get_sellers_expiring_soon()
    your_username = get_config("your_username", "yourusername")
    for uid in expiring:
        client = get_seller(uid)
        if not client: continue
        expires = client["expires"].strftime("%d %b %Y")
        try:
            await context.bot.send_message(
                uid,
                f"⏰ *Renewal reminder*\n\n"
                f"Your system expires on *{expires}*.\n\n"
                f"→ Renewal: $30/month\n"
                f"→ Annual: $250/year (save 30%)\n\n"
                f"DM @{your_username} to renew. System pauses automatically if not renewed.",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass
