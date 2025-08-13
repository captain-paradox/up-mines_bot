# bot.py
# Compatible with: python-telegram-bot==20.8
# Python >= 3.8

import os
import asyncio
import logging
import shutil
import uuid
import nest_asyncio
from typing import Dict, Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from fetch_emm11_data import fetch_emm11_data
from login_to_website import login_to_website
from pdf_gen import pdf_gen

# Optional: load BOT_TOKEN from .env if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")

ASK_START, ASK_END, ASK_DISTRICT = range(3)

user_sessions: Dict[int, Dict[str, Any]] = {}

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("up-mines-bot")


def create_user_dir(user_id: int) -> (str, str):
    session_id = str(uuid.uuid4())[:8]
    user_dir = os.path.join("sessions", f"{user_id}_{session_id}")
    pdf_dir = os.path.join(user_dir, "pdf")
    os.makedirs(pdf_dir, exist_ok=True)
    return user_dir, pdf_dir


def cleanup_user(user_id: int):
    session = user_sessions.pop(user_id, None)
    if not session:
        return
    folder = session.get("user_dir")
    if folder and os.path.isdir(folder):
        try:
            shutil.rmtree(folder)
            logger.info(f"🧹 Cleaned up session folder for user {user_id}")
        except Exception as e:
            logger.warning(f"Failed to cleanup user {user_id} dir {folder}: {e}")


async def periodic_cleanup():
    """Runs every 24 hours to clean up all sessions."""
    while True:
        logger.info("🧹 Starting scheduled cleanup of all user sessions...")
        # Get a list of all user_ids to avoid modifying dict while iterating
        all_users = list(user_sessions.keys())
        for uid in all_users:
            try:
                cleanup_user(uid)
            except Exception as e:
                logger.error(f"Error cleaning user {uid}: {e}")

        # Also remove orphan folders in sessions/ if any
        if os.path.exists("sessions"):
            for folder in os.listdir("sessions"):
                folder_path = os.path.join("sessions", folder)
                try:
                    shutil.rmtree(folder_path)
                except Exception as e:
                    logger.warning(f"Failed to remove orphan folder {folder_path}: {e}")

        logger.info("✅ Scheduled cleanup complete.")
        await asyncio.sleep(24 * 60 * 60)  # Wait 24 hours


async def safe_send(chat_id: int, context: ContextTypes.DEFAULT_TYPE, text: str):
    try:
        await context.bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        logger.error(f"Send message failed: {e}")


# --- Conversation handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_sessions:
        user_dir, pdf_dir = create_user_dir(user_id)
        user_sessions[user_id] = {
            "data": [],
            "tp_num_list": [],
            "user_dir": user_dir,
            "pdf_dir": pdf_dir,
            "lock": asyncio.Lock(),
        }
    await update.message.reply_text("Welcome! Please enter the start number:")
    return ASK_START


async def ask_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        start = int(update.message.text)
        context.user_data["start"] = start
        await update.message.reply_text("Got it. Now enter the end number:")
        return ASK_END
    except ValueError:
        await update.message.reply_text("⚠️ Please enter a valid number.")
        return ASK_START


async def ask_end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        end = int(update.message.text)
        context.user_data["end"] = end
        await update.message.reply_text("Now, please enter the district name:")
        return ASK_DISTRICT
    except ValueError:
        await update.message.reply_text("⚠️ Please enter a valid number.")
        return ASK_END


async def ask_district(update: Update, context: ContextTypes.DEFAULT_TYPE):
    district = update.message.text.strip()
    user_id = update.effective_user.id
    start = context.user_data.get("start")
    end = context.user_data.get("end")

    if user_id not in user_sessions:
        user_dir, pdf_dir = create_user_dir(user_id)
        user_sessions[user_id] = {
            "data": [],
            "tp_num_list": [],
            "user_dir": user_dir,
            "pdf_dir": pdf_dir,
            "lock": asyncio.Lock(),
        }

    session = user_sessions[user_id]
    session["start"] = start
    session["end"] = end
    session["district"] = district
    session["data"].clear()
    session["tp_num_list"].clear()

    await update.message.reply_text(f"🔎 Fetching data for district: {district}...")

    async def send_entry(entry):
        msg = (
            f"{entry.get('eMM11_num','')}\n"
            f"{entry.get('destination_district','')}\n"
            f"{entry.get('destination_address','')}\n"
            f"{entry.get('quantity_to_transport','')}\n"
            f"{entry.get('generated_on','')}"
        )
        await safe_send(update.effective_chat.id, context, msg)
        session["data"].append(entry)

    async def run_fetch():
        try:
            async with session["lock"]:
                await fetch_emm11_data(start, end, district, data_callback=send_entry)

            if session["data"]:
                keyboard = [
                    [InlineKeyboardButton("🔁 Start Again", callback_data="start_again")],
                    [InlineKeyboardButton("🔐 Login & Process", callback_data="login_process")],
                    [InlineKeyboardButton("❌ Exit", callback_data="exit_process")],
                ]
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="✅ Data fetched. What would you like to do next?",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
            else:
                await safe_send(update.effective_chat.id, context, "⚠️ No data found.")
                cleanup_user(user_id)
        except Exception as e:
            logger.exception(f"Fetch failed for user {user_id}: {e}")
            await safe_send(update.effective_chat.id, context, f"❌ Error while fetching: {e}")

    asyncio.create_task(run_fetch())
    return ConversationHandler.END


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Keep your existing button logic unchanged
    pass  # <-- You will paste your existing button_handler code here


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_user(update.effective_user.id)
    await update.message.reply_text("🚫 Operation cancelled.")
    return ConversationHandler.END


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)
    if not session:
        await update.message.reply_text("No active session. Use /start to begin.")
        return
    count = len(session.get("data", []))
    await update.message.reply_text(
        f"👤 User: {user_id}\n📦 Entries fetched: {count}\n📄 PDFs dir: {session.get('pdf_dir')}"
    )


async def run_bot():
    os.makedirs("sessions", exist_ok=True)

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_start)],
            ASK_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_end)],
            ASK_DISTRICT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_district)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("cancel", cancel))

    # Start cleanup task in background
    asyncio.create_task(periodic_cleanup())

    logger.info("🤖 Bot is starting...")
    await app.run_polling(close_loop=False)


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except RuntimeError as e:
        if "already running" in str(e):
            nest_asyncio.apply()
            loop = asyncio.get_event_loop()
            loop.run_until_complete(run_bot())
        else:
            raise
