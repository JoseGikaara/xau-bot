# handlers/seller.py
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler, CommandHandler,
                           MessageHandler, CallbackQueryHandler, filters)
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

FAQ_RESPONSES = {
    "lot size":     "📊 *Lot Size Guide*\n• $50 account → 0.01 lots\n• $500 account → 0.1 lots\n• $5,000 account → 1.0 lot\n⚠️ _Never risk more than 2% per trade._",
    "how to enter": "📌 *Entering a Trade*\n1. Open your broker\n2. Select the pair\n3. Enter at or near the Entry price\n4. Set SL and TP exactly as shown\n5. Confirm lot size before executing",
    "still valid":  "🕒 *Is the signal still valid?*\nValid until:\n→ Admin posts a /close update\n→ Price moves 30+ pips beyond entry\nIf unsure — *wait for the next signal.*",
    "tp hit":       "✅ Check the latest /close update from the admin.",
    "sl hit":       "❌ Check the latest /close update. Stay disciplined — next setup is coming.",
    "when signal":  "⏰ Signals post during London session: 10am–1pm EAT every weekday.",
}


def seller_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([
        ["🔗 Connect Channel",  "📡 Post Signal to Channel"],
        ["📋 Format Signal",    "📊 Signal History"],
        ["📈 Results",          "📖 Guide"],
        ["⚙️ My Settings"],
    ], resize_keyboard=True)


async def show_seller_menu(update: Update, context: ContextTypes.DEFAULT_TYPE,
                            via_callback: bool = False):
    if via_callback:
        user_id = update.callback_query.from_user.id
    else:
        user_id = update.effective_user.id

    active = is_seller_active(user_id)
    status = "✅ *System active*" if active else "⏸️ *System paused — contact support to activate*"
    client = get_seller(user_id)
    channel = client.get("channel", "not connected") if client else "not connected"

    text = (
        f"📢 *Signal Seller Dashboard*\n━━━━━━━━━━━━━━━━━━\n"
        f"{status}\n"
        f"📡 Channel: `{channel}`\n\n"
        "Choose an option 👇"
    )

    if via_callback:
        await update.callback_query.edit_message_text(
            text, parse_mode=ParseMode.MARKDOWN
        )
        # Send the keyboard as a separate message
        await update.callback_query.message.reply_text(
            "Use the menu below 👇",
            reply_markup=seller_keyboard(),
        )
    else:
        await update.message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN,
            reply_markup=seller_keyboard(),
        )


# ── Connect Channel ───────────────────────────────────────────

async def connect_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_active_seller(update, context): return
    context.user_data["awaiting"] = "channel"
    await update.message.reply_text(
        "🔗 *Connect your Telegram channel*\n\n"
        "Type your channel username (with @):\n"
        "Example: `@mygoldsignals`\n\n"
        "_Make sure you added this bot as admin in that channel._",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Post Signal to Channel ────────────────────────────────────

async def post_signal_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_active_seller(update, context): return
    client = get_seller(update.effective_user.id)
    channel = client.get("channel", "") if client else ""
    if not channel:
        await update.message.reply_text(
            "⚠️ No channel connected yet.\nUse *🔗 Connect Channel* first.",
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
        f"*Preview:*\n\n{preview}\n\n─────\nPost to *{channel}*?",
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
        await query.edit_message_text(f"✅ Posted to *{channel}*!", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await query.edit_message_text(
            f"❌ Failed. Make sure bot is admin in *{channel}*.\n`{e}`",
            parse_mode=ParseMode.MARKDOWN)


# ── Format Signal ─────────────────────────────────────────────

async def format_signal_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_active_seller(update, context): return
    context.user_data["awaiting"] = "fmt_pair"
    await update.message.reply_text(
        "📋 *Format your signal*\n\nWhat pair? (e.g. XAUUSD, EURUSD)",
        parse_mode=ParseMode.MARKDOWN)


# ── Signal History ────────────────────────────────────────────

async def signal_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_active_seller(update, context): return
    history = get_signal_history(update.effective_user.id)
    if not history:
        await update.message.reply_text("No signals posted yet."); return
    lines = ["📊 *Last 5 signals:*\n"]
    for i, s in enumerate(history, 1):
        lines.append(f"*#{i}* {s.get('pair','?')} {s.get('direction','')} @ {s.get('entry','')} → {s.get('channel','?')}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ── /close ────────────────────────────────────────────────────

async def close_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_active_seller(update, context): return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/close PAIR TP|SL [close_price]`\n\nExamples:\n"
            "`/close XAUUSD TP 2345.50`\n`/close EURUSD SL`",
            parse_mode=ParseMode.MARKDOWN); return

    pair_raw = args[0].upper().replace("/", "")
    pair_fmt = f"{pair_raw[:3]}/{pair_raw[3:]}" if len(pair_raw) == 6 else pair_raw
    outcome  = args[1].upper()
    close_price = float(args[2]) if len(args) >= 3 else 0.0

    if outcome not in ("TP", "SL"):
        await update.message.reply_text("Outcome must be TP or SL."); return

    user_id = update.effective_user.id
    history = get_signal_history(user_id)
    entry = direction = ""
    for h in history:
        if h.get("pair", "").replace("/", "") == pair_raw:
            entry = h.get("entry", 0.0)
            direction = h.get("direction", "")
            break

    record_trade_result(user_id, pair_fmt, direction, outcome.lower(), entry, close_price)

    if outcome == "TP":
        close_msg = (
            f"✅ *{pair_fmt} — TRADE CLOSED*\n━━━━━━━━━━━━━━━━━━\n"
            f"Outcome: *TP HIT* 🎯\n"
            + (f"Close price: `{close_price}`\n" if close_price else "")
            + "Congratulations to everyone who followed! 💰\n\n_Stay ready for the next setup._"
        )
    else:
        close_msg = (
            f"❌ *{pair_fmt} — TRADE CLOSED*\n━━━━━━━━━━━━━━━━━━\n"
            f"Outcome: *SL HIT* 🛑\n"
            + (f"Close price: `{close_price}`\n" if close_price else "")
            + "Stay disciplined — one loss doesn't define your account. 💪\n\n_Next setup coming soon._"
        )

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
        parse_mode=ParseMode.MARKDOWN)


# ── /results ─────────────────────────────────────────────────

async def results_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_active_seller(update, context): return
    user_id = update.effective_user.id
    s = get_results_summary(user_id)
    w, m, a = s["week"], s["month"], s["all"]

    def bar(rate):
        return "█" * round(rate/10) + "░" * (10 - round(rate/10)) + f" {rate}%"

    recent_lines = []
    for r in s["recent"]:
        emoji = "✅" if r["outcome"] == "tp" else "❌"
        recent_lines.append(f"{emoji} {r['pair']} {r.get('direction','')} — {r['time'].strftime('%d %b')}")

    msg = (
        f"📈 *Signal Performance*\n━━━━━━━━━━━━━━━━━━\n\n"
        f"*This week*\nWins: {w['wins']} · Losses: {w['losses']} · Total: {w['total']}\n`{bar(w['rate'])}`\n\n"
        f"*This month*\nWins: {m['wins']} · Losses: {m['losses']} · Total: {m['total']}\n`{bar(m['rate'])}`\n\n"
        f"*All time*\nWins: {a['wins']} · Losses: {a['losses']} · Total: {a['total']}\n`{bar(a['rate'])}`\n\n"
        f"━━━━━━━━━━━━━━━━━━\n*Recent trades:*\n"
        + ("\n".join(recent_lines) if recent_lines else "_No trades recorded yet._")
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

    if a["total"] > 0:
        client = get_seller(user_id)
        vip_link = (client.get("vip_link") if client else "") or get_config("vip_link", "")
        share_text = (
            f"📊 *Our Signal Performance*\n━━━━━━━━━━━━━━━━━━\n"
            f"🗓️ This week:  *{w['wins']} wins / {w['losses']} losses* ({w['rate']}%)\n"
            f"📅 This month: *{m['wins']} wins / {m['losses']} losses* ({m['rate']}%)\n"
            f"🏆 All time:   *{a['wins']} wins / {a['losses']} losses* ({a['rate']}%)\n"
            f"━━━━━━━━━━━━━━━━━━\n_Join our VIP group for premium signals_ 👇"
        )
        if vip_link:
            share_text += f"\n\n👉 [Upgrade to VIP]({vip_link})"
        context.user_data["results_share_text"] = share_text
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📢 Post results to channel", callback_data="post_results"),
        ]])
        await update.message.reply_text("Share your results with your group?", reply_markup=kb)


async def post_results_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    client = get_seller(user_id)
    channel = client.get("channel", "") if client else ""
    if not channel:
        await query.edit_message_text("⚠️ No channel connected. Use 🔗 Connect Channel first."); return
    share_text = context.user_data.get("results_share_text", "")
    try:
        await context.bot.send_message(channel, share_text, parse_mode=ParseMode.MARKDOWN)
        await query.edit_message_text(f"✅ Results posted to *{channel}*!", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await query.edit_message_text(f"❌ Failed: `{e}`", parse_mode=ParseMode.MARKDOWN)


# ── /mygroup ─────────────────────────────────────────────────

async def mygroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        await update.message.reply_text(
            "⚠️ Run this inside your *signal group*, not here.",
            parse_mode=ParseMode.MARKDOWN); return
    await update.message.reply_text(
        f"✅ *Group detected!*\n\nName: *{chat.title}*\n"
        f"Chat ID: `{chat.id}`\n"
        f"Username: `{'@'+chat.username if chat.username else 'No username — use Chat ID above'}`\n\n"
        "Send this info to your system provider to complete setup.",
        parse_mode=ParseMode.MARKDOWN)


# ── /setvip ───────────────────────────────────────────────────

async def setvip_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_active_seller(update, context): return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /setvip https://t.me/your_vip_link"); return
    set_seller_vip_link(update.effective_user.id, args[0].strip())
    await update.message.reply_text(f"✅ VIP link set to:\n{args[0].strip()}")


# ── /guide ────────────────────────────────────────────────────

async def guide_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    client = get_seller(user_id)
    vip_link = (client.get("vip_link") if client else "") or get_config("vip_link", "https://t.me/yourusername")
    your_username = get_config("your_username", "yourusername")
    await update.message.reply_text(
        "📖 *Getting Started Guide*\n━━━━━━━━━━━━━━━━━━\n\n"
        "*How signals work:*\n1. Wait for a signal alert\n"
        "2. Open your broker, select the pair\n3. Enter near the Entry price\n"
        "4. Set TP and SL exactly as shown\n5. Wait for the close update\n\n"
        "⚠️ *Risk warning*\n_Forex trading involves significant risk. Never trade money you cannot afford to lose._\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔐 *VIP access:* [Upgrade here]({vip_link})\n"
        f"❓ *Support:* @{your_username}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── Text handler for multi-step flows ─────────────────────────

async def faq_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return

    # First check if we're in a multi-step flow
    awaiting = context.user_data.get("awaiting")
    text = update.message.text.strip()

    # Trader account setup is handled in trader.py text_router
    from handlers.trader import text_router
    if awaiting in ("balance", "risk", "calc_balance", "calc_risk"):
        await text_router(update, context)
        return

    # Seller channel connection
    if awaiting == "channel":
        channel = text if text.startswith("@") else "@" + text
        set_seller_channel(update.effective_user.id, channel)
        context.user_data["awaiting"] = None
        await update.message.reply_text(
            f"✅ Channel *{channel}* connected!\n\nNow use *📡 Post Signal to Channel* to post your first signal.",
            parse_mode=ParseMode.MARKDOWN, reply_markup=seller_keyboard())
        return

    # Seller format signal flow
    if awaiting == "fmt_pair":
        context.user_data["fmt_pair"] = text.upper()
        context.user_data["awaiting"] = "fmt_dir"
        await update.message.reply_text("Direction? Type BUY or SELL")
        return

    if awaiting == "fmt_dir":
        if text.upper() not in ("BUY", "SELL"):
            await update.message.reply_text("Type BUY or SELL"); return
        context.user_data["fmt_dir"] = text.upper()
        context.user_data["awaiting"] = "fmt_entry"
        await update.message.reply_text("Entry price?")
        return

    if awaiting == "fmt_entry":
        try:
            context.user_data["fmt_entry"] = float(text)
            context.user_data["awaiting"] = "fmt_tp1"
            await update.message.reply_text("TP1 (first take profit)?")
        except ValueError:
            await update.message.reply_text("Enter a valid price number.")
        return

    if awaiting == "fmt_tp1":
        try:
            context.user_data["fmt_tp1"] = float(text)
            context.user_data["awaiting"] = "fmt_tp2"
            await update.message.reply_text("TP2 (second take profit)?")
        except ValueError:
            await update.message.reply_text("Enter a valid price number.")
        return

    if awaiting == "fmt_tp2":
        try:
            context.user_data["fmt_tp2"] = float(text)
            context.user_data["awaiting"] = "fmt_sl"
            await update.message.reply_text("Stop Loss?")
        except ValueError:
            await update.message.reply_text("Enter a valid price number.")
        return

    if awaiting == "fmt_sl":
        try:
            sl = float(text)
            d = context.user_data
            msg = format_custom_signal(d["fmt_pair"], d["fmt_dir"], d["fmt_entry"],
                                        d["fmt_tp1"], d["fmt_tp2"], sl)
            context.user_data["awaiting"] = None
            user_id = update.effective_user.id
            client = get_seller(user_id)
            channel = client.get("channel", "") if client else ""
            add_signal_to_history(user_id, {
                "text": msg, "channel": channel,
                "pair": d["fmt_pair"], "direction": d["fmt_dir"], "entry": d["fmt_entry"],
            })
            kb = None
            if channel:
                context.user_data["pending_signal"] = msg
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("📡 Post to channel", callback_data=f"post_confirm|{channel}"),
                ]])
            await update.message.reply_text(f"*Formatted signal:*\n\n{msg}",
                                             parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
        except ValueError:
            await update.message.reply_text("Enter a valid price number.")
        return

    # Risk calc flow
    if awaiting == "calc_balance":
        try:
            balance = float(text.replace(",", "").replace("$", ""))
            context.user_data["calc_balance"] = balance
            context.user_data["awaiting"] = "calc_risk"
            await update.message.reply_text("Now enter your risk % (e.g. 1 or 2):")
        except ValueError:
            await update.message.reply_text("Enter a valid number.")
        return

    if awaiting == "calc_risk":
        try:
            from services.signal_engine import calculate_lots_only
            risk = float(text.replace("%", ""))
            balance = context.user_data.get("calc_balance", 0)
            lot_size, max_loss = calculate_lots_only(balance, risk)
            context.user_data["awaiting"] = None
            await update.message.reply_text(
                f"🧮 *Risk Calculator Result*\n━━━━━━━━━━━━━━━━━━\n"
                f"💰 Balance: *${balance:,.2f}*\n"
                f"⚡ Risk: *{risk}%* = *${balance * risk / 100:,.2f}*\n\n"
                f"📊 Lot size: *{lot_size}*\n"
                f"💸 Max loss: *${max_loss:,.2f}*",
                parse_mode=ParseMode.MARKDOWN)
        except ValueError:
            await update.message.reply_text("Enter a valid number.")
        return

    # FAQ auto-replies
    text_lower = text.lower()
    for keyword, response in FAQ_RESPONSES.items():
        if keyword in text_lower:
            await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
            return


# ── Dummy conversation handlers (kept for import compatibility) ─

def get_channel_conversation():
    return ConversationHandler(
        entry_points=[CommandHandler("noop_channel", guide_command)],
        states={}, fallbacks=[],
    )

def get_format_conversation():
    return ConversationHandler(
        entry_points=[CommandHandler("noop_format", guide_command)],
        states={}, fallbacks=[],
    )