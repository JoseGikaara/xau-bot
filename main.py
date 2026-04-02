#!/usr/bin/env python3
import asyncio
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
load_dotenv()

from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters,
)
from config.settings import BOT_TOKEN
from handlers.trader import (
    start_command, get_signal, learn_strategy, settings, my_plan,
    mode_callback, risk_calc_start,
)
from handlers.seller import (
    post_signal_to_channel, signal_history, guide_command,
    faq_listener, mygroup_command, setvip_command,
    post_confirm_callback, post_results_callback,
    close_command, results_command, format_signal_start,
    connect_channel,
)
from handlers.master import (
    activate_command, suspend_command, clients_command,
    broadcast_command, grantpro_command,
    myconfig_command, setconfig_command,
)
from services.scheduler import setup_scheduler

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass

def start_health_server():
    server = HTTPServer(("0.0.0.0", 8080), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info("Health server on port 8080")


async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN not set in .env")

    start_health_server()

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",     start_command))
    app.add_handler(CommandHandler("guide",     guide_command))
    app.add_handler(CommandHandler("mygroup",   mygroup_command))
    app.add_handler(CommandHandler("setvip",    setvip_command))
    app.add_handler(CommandHandler("close",     close_command))
    app.add_handler(CommandHandler("results",   results_command))
    app.add_handler(CommandHandler("myconfig",  myconfig_command))
    app.add_handler(CommandHandler("setconfig", setconfig_command))
    app.add_handler(CommandHandler("activate",  activate_command))
    app.add_handler(CommandHandler("suspend",   suspend_command))
    app.add_handler(CommandHandler("clients",   clients_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("grantpro",  grantpro_command))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(mode_callback,         pattern=r"^mode_"))
    app.add_handler(CallbackQueryHandler(post_confirm_callback, pattern=r"^post_confirm\|"))
    app.add_handler(CallbackQueryHandler(post_confirm_callback, pattern=r"^post_cancel$"))
    app.add_handler(CallbackQueryHandler(post_results_callback, pattern=r"^post_results$"))

    # Keyboard buttons — trader
    app.add_handler(MessageHandler(filters.Regex("^📊 Get Signal$"),     get_signal))
    app.add_handler(MessageHandler(filters.Regex("^🧮 Risk Calculator$"), risk_calc_start))
    app.add_handler(MessageHandler(filters.Regex("^📚 Learn Strategy$"), learn_strategy))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ Settings$"),       settings))
    app.add_handler(MessageHandler(filters.Regex("^💰 My Plan$"),         my_plan))

    # Keyboard buttons — seller
    app.add_handler(MessageHandler(filters.Regex("^🔗 Connect Channel$"),          connect_channel))
    app.add_handler(MessageHandler(filters.Regex("^📡 Post Signal to Channel$"),   post_signal_to_channel))
    app.add_handler(MessageHandler(filters.Regex("^📋 Format Signal$"),            format_signal_start))
    app.add_handler(MessageHandler(filters.Regex("^📊 Signal History$"),           signal_history))
    app.add_handler(MessageHandler(filters.Regex("^📈 Results$"),                  results_command))
    app.add_handler(MessageHandler(filters.Regex("^⚙️ My Settings$"),              settings))
    app.add_handler(MessageHandler(filters.Regex("^📖 Guide$"),                    guide_command))

    # Catch-all text handler (FAQs + multi-step flows)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, faq_listener))

    setup_scheduler(app)

    logger.info("🤖 XAU Bot running. Press Ctrl+C to stop.")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=["message", "callback_query"])
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())