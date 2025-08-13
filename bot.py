# bot.py
# Compatible with: python-telegram-bot==20.8
# Python >= 3.8

import os
import asyncio
import logging
import shutil
import uuid
import nest_asyncio  # for environments where an event loop is already running (e.g., Jupyter)
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

BOT_TOKEN = os.getenv("BOT_TOKEN", "7933257148:AAHf7HUyBtjQbnzlUqJpGwz0S2yJfC33mqw")

# Conversation states
ASK_START, ASK_END, ASK_DISTRICT = range(3)

# Per-user in-memory sessions
# user_sessions[user_id] = {
#   start, end, district, data[list], tp_num_list[list], user_dir, pdf_dir, lock(asyncio.Lock)
# }
user_sessions: Dict[int, Dict[str, Any]] = {}

# ---------- Logging ----------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("up-mines-bot")


# ---------- Helpers ----------
def create_user_dir(user_id: int) -> (str, str): # type: ignore
    """Create isolated session folder for this user (unique per run)."""
    session_id = str(uuid.uuid4())[:8]
    user_dir = os.path.join("sessions", f"{user_id}_{session_id}")
    pdf_dir = os.path.join(user_dir, "pdf")
    os.makedirs(pdf_dir, exist_ok=True)
    return user_dir, pdf_dir


def cleanup_user(user_id: int):
    """Delete session folder and remove from memory."""
    session = user_sessions.pop(user_id, None)
    if not session:
        return
    folder = session.get("user_dir")
    if folder and os.path.isdir(folder):
        try:
            shutil.rmtree(folder)
        except Exception as e:
            logger.warning("Failed to cleanup user %s dir %s: %s", user_id, folder, e)


async def safe_send(chat_id: int, context: ContextTypes.DEFAULT_TYPE, text: str):
    """Send message with safety."""
    try:
        await context.bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        logger.error("Send message failed: %s", e)


# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Init a fresh session container with an asyncio lock to serialize this user's actions
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

    # Ensure user session exists & has lock
    if user_id not in user_sessions:
        user_dir, pdf_dir = create_user_dir(user_id)
        user_sessions[user_id] = {
            "data": [],
            "tp_num_list": [],
            "user_dir": user_dir,
            "pdf_dir": pdf_dir,
            "lock": asyncio.Lock(),
        }

    # Update session core fields
    session = user_sessions[user_id]
    session["start"] = start
    session["end"] = end
    session["district"] = district
    session["data"].clear()
    session["tp_num_list"].clear()

    await update.message.reply_text(f"🔎 Fetching data for district: {district}...")

    async def send_entry(entry):
        # Stream entries to the user as they arrive
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
            # Serialize this user's heavy operations
            async with session["lock"]:
                # Your function must be async; if it's sync, wrap with asyncio.to_thread
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
            logger.exception("Fetch failed for user %s: %s", user_id, e)
            await safe_send(update.effective_chat.id, context, f"❌ Error while fetching: {e}")

    # Run concurrently so other users aren't blocked
    asyncio.create_task(run_fetch())
    return ConversationHandler.END


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    session = user_sessions.get(user_id)
    if not session:
        await query.edit_message_text("⚠️ Session expired. Please start again with /start.")
        return

    if query.data == "start_again":
        await query.edit_message_text("🔁 Restarting...")
        cleanup_user(user_id)
        await context.bot.send_message(chat_id=query.message.chat.id, text="/start")
        return

    if query.data == "exit_process":
        await query.edit_message_text("❌ Exiting session.")
        cleanup_user(user_id)
        return

    if query.data == "login_process":
        await query.edit_message_text("🔐 Logging in and processing data...")

        async def process_data():
            try:
                async with session["lock"]:
                    async def log_callback(msg):
                        await safe_send(query.message.chat.id, context, msg)

                    # If login_to_website is blocking/sync, wrap it:
                    # await asyncio.to_thread(login_to_website, session["data"], log_callback=log_callback)
                    await login_to_website(session["data"], log_callback=log_callback)

                    session["tp_num_list"] = [e.get("eMM11_num", "") for e in session["data"] if e.get("eMM11_num")]
                keyboard = [
                    [InlineKeyboardButton("📄 Generate PDF", callback_data="generate_pdf")],
                    [InlineKeyboardButton("❌ Exit", callback_data="exit_process")],
                ]
                await context.bot.send_message(
                    chat_id=query.message.chat.id,
                    text="✅ Processing done. Click below to generate PDF.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
            except Exception as e:
                logger.exception("Login/process failed for user %s: %s", user_id, e)
                await safe_send(query.message.chat.id, context, f"❌ Error during process: {e}")

        asyncio.create_task(process_data())
        return

    if query.data == "generate_pdf":
        tp_list = session.get("tp_num_list", [])
        if not tp_list:
            await safe_send(query.message.chat.id, context, "⚠️ No TP numbers found.")
            return

        async def generate():
            try:
                async with session["lock"]:
                    # If pdf_gen is CPU/IO heavy sync, wrap it:
                    # await asyncio.to_thread(pdf_gen, tp_list, output_dir=session["pdf_dir"], log_callback=..., send_pdf_callback=None)
                    await pdf_gen(
                        tp_list,
                        output_dir=session["pdf_dir"],
                        log_callback=lambda msg: asyncio.create_task(
                            safe_send(query.message.chat.id, context, msg)
                        ),
                        send_pdf_callback=None,
                    )
                # Show buttons to download generated PDFs
                keyboard = [
                    [InlineKeyboardButton(f"📎 {tp}.pdf", callback_data=f"pdf_{tp}")]
                    for tp in tp_list
                ]
                keyboard.append([InlineKeyboardButton("❌ Exit", callback_data="exit_process")])
                await context.bot.send_message(
                    chat_id=query.message.chat.id,
                    text="📄 Click to download your PDFs:",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
            except Exception as e:
                logger.exception("PDF gen failed for user %s: %s", user_id, e)
                await safe_send(query.message.chat.id, context, f"❌ Error during PDF generation: {e}")

        asyncio.create_task(generate())
        return

    if query.data.startswith("pdf_"):
        tp_num = query.data.split("_", 1)[1]
        pdf_path = os.path.join(session["pdf_dir"], f"{tp_num}.pdf")
        if os.path.exists(pdf_path):
            try:
                with open(pdf_path, "rb") as f:
                    await context.bot.send_document(
                        chat_id=query.message.chat.id,
                        document=f,
                        filename=f"{tp_num}.pdf",
                        caption=f"📎 TP: {tp_num}",
                    )
            except Exception as e:
                logger.error("Sending PDF failed: %s", e)
                await safe_send(query.message.chat.id, context, "❌ Failed to send PDF.")
        else:
            await safe_send(query.message.chat.id, context, "❌ PDF not found.")
        return


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_user(update.effective_user.id)
    await update.message.reply_text("🚫 Operation cancelled.")
    return ConversationHandler.END


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Simple health/status command per user."""
    user_id = update.effective_user.id
    session = user_sessions.get(user_id)
    if not session:
        await update.message.reply_text("No active session. Use /start to begin.")
        return
    count = len(session.get("data", []))
    await update.message.reply_text(
        f"👤 User: {user_id}\n"
        f"📦 Entries fetched: {count}\n"
        f"📄 PDFs dir: {session.get('pdf_dir')}"
    )


# ---------- Boot ----------
async def run_bot():
    os.makedirs("sessions", exist_ok=True)

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Conversation
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_START: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_start)],
            ASK_END: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_end)],
            ASK_DISTRICT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_district)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="main_conversation",
        persistent=False,
    )

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("cancel", cancel))

    logger.info("🤖 Bot is starting...")
    await app.run_polling(
        allowed_updates=None,              # PTB manages what it needs
        stop_signals=None,                 # PTB handles signals internally
        close_loop=False,                  # prevents closing an external running loop
    )


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except RuntimeError as e:
        # Works in notebooks/async shells too
        if "already running" in str(e):
            nest_asyncio.apply()
            loop = asyncio.get_event_loop()
            loop.run_until_complete(run_bot())
        else:
            raise
