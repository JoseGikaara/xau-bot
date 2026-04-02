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
    # Clear any stuck conversation state
    context.user_data.clear()
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

    if query.data == "mode_seller":
        set_user_mode(user_id, "seller")
        from handlers.seller import show_seller_menu
        await show_seller_menu(update, context, via_callback=True)
        return

    if query.data == "mode_trader":
        set_user_mode(user_id, "trader")
        await query.edit_message_text(
            "📊 *Trader Mode activated.*\n\n"
            "What is your trading account balance in USD?\n"
            "_(e.g. 500 or 1000)_",
            parse_mode=ParseMode.MARKDOWN,
        )
        context.user_data["awaiting"] = "balance"


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes text messages based on what we're waiting for."""
    awaiting = context.user_data.get("awaiting")
    text = update.message.text.strip()

    if awaiting == "balance":
        try:
            balance = float(text.replace(",", "").replace("$", ""))
            context.user_data["balance"] = balance
            context.user_data["awaiting"] = "risk"
            await update.message.reply_text(
                f"✅ Balance: *${balance:,.2f}*\n\nWhat risk % per trade? (e.g. 1 or 2)",
                parse_mode=ParseMode.MARKDOWN,
            )
        except ValueError:
            await update.message.reply_text("Please enter a number, e.g. 500")
        return True

    if awaiting == "risk":
        try:
            risk = float(text.replace("%", ""))
            if not (0.1 <= risk <= 10):
                raise ValueError
            balance = context.user_data.get("balance", 0)
            set_user_account(update.effective_user.id, balance, risk)
            context.user_data["awaiting"] = None
            await update.message.reply_text(
                f"✅ *Account configured!*\n\n"
                f"💰 Balance: *${balance:,.2f}*\n"
                f"⚡ Risk: *{risk}%*\n\n"
                "Choose an option 👇",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=trader_keyboard(),
            )
        except ValueError:
            await update.message.reply_text("Enter a number between 0.1 and 10, e.g. 1")
        return True

    return False


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
    context.user_data["awaiting"] = "calc_balance"
    await update.message.reply_text("🧮 *Risk Calculator*\n\nEnter your balance in USD:",
                                     parse_mode=ParseMode.MARKDOWN)


async def learn_strategy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 *London Breakout Strategy — XAUUSD*\n━━━━━━━━━━━━━━━━━━\n\n"
        "*What is it?*\nGold is most volatile when London opens at 10am EAT. "
        "Price breaks out of the tight Asian range — we trade that breakout.\n\n"
        "*When to trade:*\n✅ 10:00am – 1:00pm EAT\n"
        "❌ Avoid Fridays after 12pm\n❌ Avoid NFP, Fed, CPI news\n\n"
        "*Entry rules:*\n1. Identify Asian range high and low\n"
        "2. BUY above Asian high OR SELL below Asian low\n"
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
        "To change mode or reset, type /start",
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
    # Dummy — kept for import compatibility, not used
    return ConversationHandler(
        entry_points=[CommandHandler("noop_setup", start_command)],
        states={},
        fallbacks=[],
    )


def get_calc_conversation():
    # Dummy — kept for import compatibility, not used
    return ConversationHandler(
        entry_points=[CommandHandler("noop_calc", start_command)],
        states={},
        fallbacks=[],
    )