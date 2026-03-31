# handlers/trader.py
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (ContextTypes, ConversationHandler, CommandHandler,
                           MessageHandler, CallbackQueryHandler, filters)
from telegram.constants import ParseMode

from config.database import (
    get_or_create_user, set_user_mode, set_user_account,
    get_user_tier, is_pro
)
from config.settings import PRICING
from services.signal_engine import generate_london_signal, format_signal_message, calculate_lots_only
from services.paywall import require_pro

ASK_BALANCE, ASK_RISK = range(2)
CALC_BALANCE, CALC_RISK = range(2, 4)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.username or "")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 I want to trade (Trader Mode)", callback_data="mode_trader")],
        [InlineKeyboardButton("📢 I run a signal group (Seller Mode)", callback_data="mode_seller")],
    ])
    await update.message.reply_text(
        f"👋 Welcome, {user.first_name}!\n\n"
        "I'm your *XAUUSD London Breakout System* — choose your path:\n\n"
        "📊 *Trader Mode* — get live gold signals with your exact lot size calculated\n"
        "📢 *Seller Mode* — automate your Telegram signal group\n",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb,
    )


async def mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "mode_trader":
        set_user_mode(user_id, "trader")
        await query.edit_message_text(
            "📊 *Trader Mode activated.*\n\n"
            "What is your trading account balance in USD?\n"
            "_(e.g. 500 or 1000)_",
            parse_mode=ParseMode.MARKDOWN,
        )
        context.user_data["state"] = "ASK_BALANCE"

    elif query.data == "mode_seller":
        set_user_mode(user_id, "seller")
        from handlers.seller import show_seller_menu
        await show_seller_menu(update, context, via_callback=True)


async def ask_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        balance = float(update.message.text.replace(",", "").replace("$", "").strip())
    except ValueError:
        await update.message.reply_text("Please enter a number, e.g. 500")
        return ASK_BALANCE
    context.user_data["balance"] = balance
    context.user_data["state"] = "ASK_RISK"
    await update.message.reply_text(
        f"✅ Balance: *${balance:,.2f}*\n\nWhat risk % per trade? (e.g. 1 or 2)",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ASK_RISK


async def ask_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        risk = float(update.message.text.replace("%", "").strip())
        if not (0.1 <= risk <= 10):
            raise ValueError
    except ValueError:
        await update.message.reply_text("Enter a number between 0.1 and 10")
        return ASK_RISK
    user_id = update.effective_user.id
    balance = context.user_data.get("balance", 0)
    set_user_account(user_id, balance, risk)
    context.user_data["state"] = None
    await update.message.reply_text(
        f"✅ *Account configured!*\n\n"
        f"💰 Balance: *${balance:,.2f}*\n"
        f"⚡ Risk: *{risk}%* = ${balance * risk / 100:,.2f} max loss\n\n"
        "Choose an option 👇",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=trader_keyboard(),
    )
    return ConversationHandler.END


def trader_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([
        ["📊 Get Signal", "🧮 Risk Calculator"],
        ["📚 Learn Strategy", "⚙️ Settings"],
        ["💰 My Plan"],
    ], resize_keyboard=True)


async def get_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_pro(update, context, "get_signal"):
        return
    user_id = update.effective_user.id
    from config.database import USERS
    user = USERS.get(user_id, {})
    await update.message.reply_text("⏳ Fetching live gold price...")
    sig = await generate_london_signal(user.get("balance", 0), user.get("risk_pct", 1.0))
    await update.message.reply_text(format_signal_message(sig), parse_mode=ParseMode.MARKDOWN)


async def risk_calc_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧮 *Risk Calculator*\n\nEnter your balance in USD:",
                                     parse_mode=ParseMode.MARKDOWN)
    return CALC_BALANCE


async def risk_calc_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        balance = float(update.message.text.replace(",", "").replace("$", "").strip())
    except ValueError:
        await update.message.reply_text("Enter a valid number.")
        return CALC_BALANCE
    context.user_data["calc_balance"] = balance
    await update.message.reply_text("Now enter your risk % (e.g. 1 or 2):")
    return CALC_RISK


async def risk_calc_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        risk = float(update.message.text.replace("%", "").strip())
    except ValueError:
        await update.message.reply_text("Enter a valid number.")
        return CALC_RISK
    balance = context.user_data.get("calc_balance", 0)
    lot_size, max_loss = calculate_lots_only(balance, risk)
    await update.message.reply_text(
        f"🧮 *Risk Calculator Result*\n━━━━━━━━━━━━━━━━━━\n"
        f"💰 Balance: *${balance:,.2f}*\n"
        f"⚡ Risk: *{risk}%* = *${balance * risk / 100:,.2f}*\n\n"
        f"📊 Lot size: *{lot_size}*\n"
        f"💸 Max loss: *${max_loss:,.2f}*",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ConversationHandler.END


async def learn_strategy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *London Breakout Strategy — XAUUSD*\n━━━━━━━━━━━━━━━━━━\n\n"
        "*What is it?*\nGold is most volatile when London opens at 10am EAT. "
        "Price breaks out of the tight Asian range — we trade that breakout.\n\n"
        "*When to trade:*\n✅ 10:00am – 1:00pm EAT\n"
        "❌ Avoid Fridays after 12pm\n❌ Avoid NFP, Fed, CPI news\n\n"
        "*Entry rules:*\n1. Identify Asian range high and low\n"
        "2. Enter BUY above Asian high OR SELL below Asian low\n"
        "3. SL = 15 pips, TP1 = 1:1, TP2 = 1:2\n"
        "4. Move SL to break-even when TP1 hits\n\n"
        "_Pro members get live signals at 7:05am EAT every weekday._",
        parse_mode=ParseMode.MARKDOWN,
    )


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    from config.database import USERS
    user = USERS.get(user_id, {})
    await update.message.reply_text(
        f"⚙️ *Your Settings*\n━━━━━━━━━━━━━━━━━━\n"
        f"💰 Balance: *${user.get('balance', 0):,.2f}*\n"
        f"⚡ Risk %: *{user.get('risk_pct', 1.0)}%*\n"
        f"🎯 Mode: *{user.get('mode', 'not set').title()}*\n"
        f"👑 Plan: *{get_user_tier(user_id).title()}*\n\n"
        "To update, type /start and set up again",
        parse_mode=ParseMode.MARKDOWN,
    )


async def my_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    current = get_user_tier(update.effective_user.id)
    lines = ["💰 *Plans & Pricing*\n━━━━━━━━━━━━━━━━━━"]
    for tier, info in PRICING.items():
        marker = "✅ Current" if tier == current else ""
        lines.append(f"\n*{info['label']}* — {info['price']} {marker}\n_{info['desc']}_")
    lines.append("\n━━━━━━━━━━━━━━━━━━\nTo upgrade, DM @yourusername")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


def get_setup_conversation():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(mode_callback, pattern="^mode_")],
        states={
            ASK_BALANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_balance)],
            ASK_RISK:    [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_risk)],
        },
        fallbacks=[CommandHandler("start", start_command)],
        per_message=False,
        per_chat=True,
    )


def get_calc_conversation():
    return ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🧮 Risk Calculator$"), risk_calc_start)],
        states={
            CALC_BALANCE: [MessageHandler(filters.TEXT & ~filters.COMMAND, risk_calc_balance)],
            CALC_RISK:    [MessageHandler(filters.TEXT & ~filters.COMMAND, risk_calc_result)],
        },
        fallbacks=[CommandHandler("start", start_command)],
    )