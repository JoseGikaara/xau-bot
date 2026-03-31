# ─────────────────────────────────────────────────────────────
# handlers/seller.py — all Signal Seller mode features
# ─────────────────────────────────────────────────────────────
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler, CommandHandler,
                           MessageHandler, filters, CallbackQueryHandler)
from telegram.constants import ParseMode

from config.database import (
    get_or_create_user, is_seller_active, get_seller,
    set_seller_channel, set_seller_vip_link,
    add_signal_to_history, get_signal_history,
    record_trade_result, get_results_summary,
)
from config.settings import get_config
from services.signal_engine import (
    generate_london_signal, format_signal_message, format_custom_signal
)
from services.paywall import require_active_seller

FORMAT_PAIR, FORMAT_DIR, FORMAT_ENTRY, FORMAT_TP1, FORMAT_TP2, FORMAT_SL = range(6)
CLOSE_PAIR, CLOSE_OUTCOME, CLOSE_PRICE = range(6, 9)

FAQ_RESPONSES = {
    "lot size":     "📊 *Lot Size Guide*\n• $50 account → 0.01 lots\n• $500 account → 0.1 lots\n• $5,000 account → 1.0 lot\n⚠️ _Never risk more than 2% per trade._",
    "how to enter": "📌 *Entering a Trade*\n1. Open your broker\n2. Select the pair in the signal\n3. Enter at or near the Entry price\n4. Set SL and TP exactly as shown\n5. Confirm lot size before executing",
    "still valid":  "🕒 *Is the signal still valid?*\nA signal is valid until:\n→ Admin posts a /close update\n→ Price moves 30+ pips beyond entry\nIf unsure — *wait for the next signal.*",
    "tp hit":       "✅ Check the latest /close update from the admin.",
    "sl hit":       "❌ Check the latest /close update from the admin. Stay disciplined — next setup is coming.",
    "when signal":  "⏰ Signals are posted during the London session: 10am–1pm EAT every weekday.",
}


# ── Keyboards ─────────────────────────────────────────────────

def seller_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([
        ["🔗 Connect Channel",  "📡 Post Signal to Channel"],
        ["📋 Format Signal",    "📊 Signal History"],
        ["📈 Results",          "📖 Guide"],
        ["⚙️ My Settings"],
    ], resize_keyboard=True)


# ── Seller dashboard ──────────────────────────────────────────

async def show_seller_menu(update: Update, context: ContextTypes.DEFAULT_TYPE,
                            via_callback: bool = False):
    user_id = (update.effective_user.id if not via_callback
               else update.callback_query.from_user.id)
    active = is_seller_active(user_id)
    status_line = "✅ *System active*" if active else "⏸️ *System paused — contact support to activate*"
    client = get_seller(user_id)
    channel = client.get("channel", "not connected") if client else "not connected"

    text = (
        f"📢 *Signal Seller Dashboard*\n━━━━━━━━━━━━━━━━━━\n"
        f"{status_line}\n📡 Channel: `{channel}`\n\nChoose an option 👇"
    )
    if via_callback:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN,
                                         reply_markup=seller_keyboard())


# ── 🔗 Connect Channel ────────────────────────────────────────

async def connect_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_active_seller(update, context): return
    await update.message.reply_text(
        "🔗 *Connect your Telegram channel*\n\n"
        "Type your channel username (with @):\nExample: `@mygoldsignals`\n\n"
        "_Make sure you've already added this bot as admin in that channel._",
        parse_mode=ParseMode.MARKDOWN,
    )
    return "AWAITING_CHANNEL"


async def save_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    channel = update.message.text.strip()
    if not channel.startswith("@"): channel = "@" + channel
    set_seller_channel(update.effective_user.id, channel)
    await update.message.reply_text(
        f"✅ Channel *{channel}* connected!\n\nNow use *📡 Post Signal to Channel* to post your first signal.",
        parse_mode=ParseMode.MARKDOWN, reply_markup=seller_keyboard(),
    )
    return ConversationHandler.END


# ── 📡 Post Signal to Channel ─────────────────────────────────

async def post_signal_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_active_seller(update, context): return
    user_id = update.effective_user.id
    client = get_seller(user_id)
    channel = client.get("channel", "") if client else ""
    if not channel:
        await update.message.reply_text(
            "⚠️ No channel connected yet. Use *🔗 Connect Channel* first.",
            parse_mode=ParseMode.MARKDOWN)
        return

    await update.message.reply_text("⏳ Fetching live gold price...")
    sig = await generate_london_signal()
    preview = format_signal_message(sig, for_channel=True)
    context.user_data["pending_signal"] = preview
    context.user_data["pending_entry"]  = sig.entry
    context.user_data["pending_pair"]   = "XAUUSD"
    context.user_data["pending_dir"]    = sig.direction

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Post to channel", callback_data=f"post_confirm|{channel}"),
        InlineKeyboardButton("❌ Cancel",           callback_data="post_cancel"),
    ]])
    await update.message.reply_text(
        f"*Preview:*\n\n{preview}\n\n─────\nPost this to *{channel}*?",
        parse_mode=ParseMode.MARKDOWN, reply_markup=kb,
    )


async def post_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "post_cancel":
        await query.edit_message_text("Cancelled."); return

    _, channel = query.data.split("|", 1)
    user_id = query.from_user.id
    preview = context.user_data.get("pending_signal", "")
    try:
        await context.bot.send_message(channel, preview, parse_mode=ParseMode.MARKDOWN)
        add_signal_to_history(user_id, {
            "text": preview, "channel": channel,
            "pair": context.user_data.get("pending_pair", "XAUUSD"),
            "direction": context.user_data.get("pending_dir", ""),
            "entry": context.user_data.get("pending_entry", 0),
        })
        await query.edit_message_text(f"✅ Signal posted to *{channel}*!", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await query.edit_message_text(
            f"❌ Failed to post. Ensure bot is admin in *{channel}*.\n`{e}`",
            parse_mode=ParseMode.MARKDOWN)


# ── 📋 Format Signal ──────────────────────────────────────────

async def format_signal_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_active_seller(update, context): return
    await update.message.reply_text(
        "📋 *Format your signal*\n\nWhat pair? (e.g. XAUUSD, EURUSD, GBPJPY)",
        parse_mode=ParseMode.MARKDOWN)
    return FORMAT_PAIR

async def format_get_dir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["fmt_pair"] = update.message.text.strip().upper()
    await update.message.reply_text("Direction? Type BUY or SELL")
    return FORMAT_DIR

async def format_get_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = update.message.text.strip().upper()
    if d not in ("BUY", "SELL"):
        await update.message.reply_text("Type BUY or SELL"); return FORMAT_DIR
    context.user_data["fmt_dir"] = d
    await update.message.reply_text("Entry price?")
    return FORMAT_ENTRY

async def format_get_tp1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: context.user_data["fmt_entry"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Enter a valid price."); return FORMAT_ENTRY
    await update.message.reply_text("TP1 (first take profit)?")
    return FORMAT_TP1

async def format_get_tp2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: context.user_data["fmt_tp1"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Enter a valid price."); return FORMAT_TP1
    await update.message.reply_text("TP2 (second take profit)?")
    return FORMAT_TP2

async def format_get_sl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: context.user_data["fmt_tp2"] = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Enter a valid price."); return FORMAT_TP2
    await update.message.reply_text("Stop Loss?")
    return FORMAT_SL

async def format_show_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try: sl = float(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Enter a valid price."); return FORMAT_SL

    d = context.user_data
    msg = format_custom_signal(d["fmt_pair"], d["fmt_dir"], d["fmt_entry"],
                                d["fmt_tp1"], d["fmt_tp2"], sl)
    user_id = update.effective_user.id
    client = get_seller(user_id)
    channel = client.get("channel", "") if client else ""
    kb = None
    if channel:
        context.user_data["pending_signal"] = msg
        context.user_data["pending_entry"]  = d["fmt_entry"]
        context.user_data["pending_pair"]   = d["fmt_pair"]
        context.user_data["pending_dir"]    = d["fmt_dir"]
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📡 Post to channel", callback_data=f"post_confirm|{channel}"),
        ]])
    add_signal_to_history(user_id, {
        "text": msg, "channel": channel,
        "pair": d["fmt_pair"], "direction": d["fmt_dir"], "entry": d["fmt_entry"],
    })
    await update.message.reply_text(f"*Formatted signal:*\n\n{msg}",
                                     parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    return ConversationHandler.END


# ── 📊 Signal History ─────────────────────────────────────────

async def signal_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_active_seller(update, context): return
    history = get_signal_history(update.effective_user.id)
    if not history:
        await update.message.reply_text("No signals posted yet."); return
    lines = ["📊 *Last 5 signals:*\n"]
    for i, s in enumerate(history, 1):
        pair = s.get("pair", "?")
        direction = s.get("direction", "")
        entry = s.get("entry", "")
        channel = s.get("channel", "?")
        lines.append(f"*#{i}* {pair} {direction} @ {entry} → {channel}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ── /close PAIR TP|SL [close_price] ──────────────────────────
# Works as a command OR as a conversation flow from the menu

async def close_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /close XAUUSD TP 2345.50
    /close EURUSD SL
    Records result + posts close announcement to channel.
    """
    if not await require_active_seller(update, context): return

    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/close PAIR TP|SL [close_price]`\n\n"
            "Examples:\n"
            "`/close XAUUSD TP 2345.50`\n"
            "`/close EURUSD SL`",
            parse_mode=ParseMode.MARKDOWN)
        return

    pair_raw = args[0].upper().replace("/", "")
    pair_fmt = f"{pair_raw[:3]}/{pair_raw[3:]}" if len(pair_raw) == 6 else pair_raw
    outcome  = args[1].upper()
    close_price = float(args[2]) if len(args) >= 3 else 0.0

    if outcome not in ("TP", "SL"):
        await update.message.reply_text("Outcome must be TP or SL."); return

    user_id = update.effective_user.id

    # Pull entry from last signal history if available
    history = get_signal_history(user_id)
    entry = 0.0
    direction = ""
    for h in history:
        if h.get("pair", "").replace("/","") == pair_raw:
            entry = h.get("entry", 0.0)
            direction = h.get("direction", "")
            break

    # Record for /results tracker
    record_trade_result(user_id, pair_fmt, direction, outcome.lower(), entry, close_price)

    # Format close announcement
    if outcome == "TP":
        close_msg = (
            f"✅ *{pair_fmt} — TRADE CLOSED*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Outcome: *TP HIT* 🎯\n"
            + (f"Close price: `{close_price}`\n" if close_price else "")
            + f"Congratulations to everyone who followed! 💰\n\n"
            f"_Stay ready for the next setup._"
        )
    else:
        close_msg = (
            f"❌ *{pair_fmt} — TRADE CLOSED*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Outcome: *SL HIT* 🛑\n"
            + (f"Close price: `{close_price}`\n" if close_price else "")
            + f"This one didn't go our way. Stay disciplined — one loss doesn't define your account. 💪\n\n"
            f"_Next setup coming soon._"
        )

    # Try to post to their channel automatically
    client = get_seller(user_id)
    channel = client.get("channel", "") if client else ""
    posted_to = ""
    if channel:
        try:
            await context.bot.send_message(channel, close_msg, parse_mode=ParseMode.MARKDOWN)
            posted_to = f"\n✅ Posted to *{channel}*"
        except Exception as e:
            posted_to = f"\n⚠️ Could not post to {channel}: `{e}`"

    await update.message.reply_text(
        f"Recorded: *{pair_fmt} {outcome}*{posted_to}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── 📈 /results — win/loss tracker ───────────────────────────

async def results_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Shows win/loss performance for this week, this month, all time.
    Also generates a shareable summary the seller can copy to their channel.
    """
    if not await require_active_seller(update, context): return

    user_id = update.effective_user.id
    s = get_results_summary(user_id)

    w  = s["week"]
    m  = s["month"]
    a  = s["all"]

    # Recent trades list
    recent_lines = []
    for r in s["recent"]:
        emoji = "✅" if r["outcome"] == "tp" else "❌"
        date  = r["time"].strftime("%d %b")
        recent_lines.append(f"{emoji} {r['pair']} {r.get('direction','')} — {date}")
    recent_str = "\n".join(recent_lines) if recent_lines else "_No trades recorded yet._"

    # Win rate bar (visual)
    def _bar(rate: int) -> str:
        filled = round(rate / 10)
        return "█" * filled + "░" * (10 - filled) + f" {rate}%"

    msg = (
        f"📈 *Signal Performance*\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"*This week*\n"
        f"Wins: {w['wins']} · Losses: {w['losses']} · Total: {w['total']}\n"
        f"`{_bar(w['rate'])}`\n\n"
        f"*This month*\n"
        f"Wins: {m['wins']} · Losses: {m['losses']} · Total: {m['total']}\n"
        f"`{_bar(m['rate'])}`\n\n"
        f"*All time*\n"
        f"Wins: {a['wins']} · Losses: {a['losses']} · Total: {a['total']}\n"
        f"`{_bar(a['rate'])}`\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"*Recent trades:*\n{recent_str}"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    # Offer shareable version
    if a["total"] > 0:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📢 Post results to channel", callback_data="post_results"),
        ]])
        context.user_data["results_share_text"] = (
            f"📊 *Our Signal Performance*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🗓️ This week:  *{w['wins']} wins / {w['losses']} losses* ({w['rate']}%)\n"
            f"📅 This month: *{m['wins']} wins / {m['losses']} losses* ({m['rate']}%)\n"
            f"🏆 All time:   *{a['wins']} wins / {a['losses']} losses* ({a['rate']}%)\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"_Join our VIP group for premium signals_ 👇"
        )
        await update.message.reply_text(
            "Want to share your results with your group?",
            reply_markup=kb,
        )


async def post_results_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    client = get_seller(user_id)
    channel = client.get("channel", "") if client else ""

    if not channel:
        await query.edit_message_text("⚠️ No channel connected. Use 🔗 Connect Channel first.")
        return

    vip_link = client.get("vip_link", get_config("vip_link"))
    share_text = context.user_data.get("results_share_text", "")
    if vip_link:
        share_text += f"\n\n👉 [Upgrade to VIP]({vip_link})"

    try:
        await context.bot.send_message(channel, share_text, parse_mode=ParseMode.MARKDOWN)
        await query.edit_message_text(f"✅ Results posted to *{channel}*!", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await query.edit_message_text(f"❌ Failed: `{e}`", parse_mode=ParseMode.MARKDOWN)


# ── /mygroup — self-onboarding ────────────────────────────────

async def mygroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        await update.message.reply_text(
            "⚠️ Run this command *inside your signal group*, not here.",
            parse_mode=ParseMode.MARKDOWN); return
    await update.message.reply_text(
        f"✅ *Group detected!*\n\n"
        f"Name: *{chat.title}*\n"
        f"Chat ID: `{chat.id}`\n"
        f"Username: `{'@'+chat.username if chat.username else 'No username (use Chat ID above)'}`\n\n"
        "Send the username or chat ID to your system provider to complete setup.",
        parse_mode=ParseMode.MARKDOWN)


# ── /setvip <link> ────────────────────────────────────────────

async def setvip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_active_seller(update, context): return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /setvip https://t.me/your_vip_link"); return
    link = args[0].strip()
    set_seller_vip_link(update.effective_user.id, link)
    await update.message.reply_text(
        f"✅ VIP link set to:\n{link}\n\nThis link now appears in /guide and VIP gate messages.")


# ── FAQ auto-reply ────────────────────────────────────────────

async def faq_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    text = update.message.text.lower()
    for keyword, response in FAQ_RESPONSES.items():
        if keyword in text:
            await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
            return


# ── /guide ────────────────────────────────────────────────────

async def guide_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    client = get_seller(user_id)
    vip_link = (client.get("vip_link") if client else "") or get_config("vip_link", "https://t.me/yourusername")
    your_username = get_config("your_username", "yourusername")

    await update.message.reply_text(
        "📖 *Getting Started Guide*\n━━━━━━━━━━━━━━━━━━\n\n"
        "*How signals work:*\n"
        "1. Wait for a signal alert\n"
        "2. Open your broker, select the pair\n"
        "3. Enter near the Entry price\n"
        "4. Set TP and SL exactly as shown\n"
        "5. Wait for the close update\n\n"
        "⚠️ *Risk warning*\n"
        "_Forex trading involves significant risk. Never trade money you cannot afford to lose._\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔐 *VIP access:* [Upgrade here]({vip_link})\n"
        f"❓ *Support:* @{your_username}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── ConversationHandlers ──────────────────────────────────────

def get_channel_conversation():
    return ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔗 Connect Channel$"), connect_channel)],
        states={"AWAITING_CHANNEL": [MessageHandler(filters.TEXT & ~filters.COMMAND, save_channel)]},
        fallbacks=[],
    )

def get_format_conversation():
    return ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📋 Format Signal$"), format_signal_start)],
        states={
            FORMAT_PAIR:  [MessageHandler(filters.TEXT & ~filters.COMMAND, format_get_dir)],
            FORMAT_DIR:   [MessageHandler(filters.TEXT & ~filters.COMMAND, format_get_entry)],
            FORMAT_ENTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, format_get_tp1)],
            FORMAT_TP1:   [MessageHandler(filters.TEXT & ~filters.COMMAND, format_get_tp2)],
            FORMAT_TP2:   [MessageHandler(filters.TEXT & ~filters.COMMAND, format_get_sl)],
            FORMAT_SL:    [MessageHandler(filters.TEXT & ~filters.COMMAND, format_show_result)],
        },
        fallbacks=[],
    )
