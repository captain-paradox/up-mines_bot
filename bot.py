import os
import asyncio
import shutil
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
)

from fetch_emm11_data import fetch_emm11_data
from login_to_website import login_to_website
from pdf_gen import pdf_gen

BOT_TOKEN = "7933257148:AAHf7HUyBtjQbnzlUqJpGwz0S2yJfC33mqw"
#kk 1

ASK_START, ASK_END, ASK_DISTRICT = range(3)

# Stores user sessions: {user_id: {...}}
user_sessions = {}


def create_user_dir(user_id):
    """Create isolated session folder for this user."""
    session_id = str(uuid.uuid4())[:8]
    user_dir = os.path.join("sessions", f"{user_id}_{session_id}")
    os.makedirs(user_dir, exist_ok=True)
    pdf_dir = os.path.join(user_dir, "pdf")
    os.makedirs(pdf_dir, exist_ok=True)
    return user_dir, pdf_dir


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    district = update.message.text
    user_id = update.effective_user.id
    start = context.user_data["start"]
    end = context.user_data["end"]

    # Create isolated session folder
    user_dir, pdf_dir = create_user_dir(user_id)

    # Store session data
    user_sessions[user_id] = {
        "start": start,
        "end": end,
        "district": district,
        "data": [],
        "tp_num_list": [],
        "user_dir": user_dir,
        "pdf_dir": pdf_dir,
    }

    await update.message.reply_text(f"🔎 Fetching data for district: {district}...")

    async def send_entry(entry):
        msg = (
            f"{entry['eMM11_num']}\n"
            f"{entry['destination_district']}\n"
            f"{entry['destination_address']}\n"
            f"{entry['quantity_to_transport']}\n"
            f"{entry['generated_on']}"
        )
        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg)
        user_sessions[user_id]["data"].append(entry)

    async def run_fetch():
        await fetch_emm11_data(start, end, district, data_callback=send_entry)

        # Once finished
        if user_sessions[user_id]["data"]:
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
            await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ No data found.")
            cleanup_user(user_id)

    asyncio.create_task(run_fetch())
    return ConversationHandler.END


def cleanup_user(user_id):
    """Delete session folder and remove from memory."""
    if user_id in user_sessions:
        folder = user_sessions[user_id]["user_dir"]
        try:
            shutil.rmtree(folder)
        except:
            pass
        user_sessions.pop(user_id, None)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if user_id not in user_sessions:
        await query.edit_message_text("⚠️ Session expired. Please start again with /start.")
        return

    session = user_sessions[user_id]

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
            async def log_callback(msg):
                await context.bot.send_message(chat_id=query.message.chat.id, text=msg)

            await login_to_website(session["data"], log_callback=log_callback)
            session["tp_num_list"] = [e["eMM11_num"] for e in session["data"]]

            keyboard = [
                [InlineKeyboardButton("📄 Generate PDF", callback_data="generate_pdf")],
                [InlineKeyboardButton("❌ Exit", callback_data="exit_process")],
            ]
            await context.bot.send_message(
                chat_id=query.message.chat.id,
                text="✅ Processing done. Click below to generate PDF.",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

        asyncio.create_task(process_data())
        return

    if query.data == "generate_pdf":
        tp_list = session.get("tp_num_list", [])
        if not tp_list:
            await context.bot.send_message(chat_id=query.message.chat.id, text="⚠️ No TP numbers found.")
            return

        async def generate():
            await pdf_gen(
                tp_list,
                output_dir=session["pdf_dir"],  # SAVE PDFs PER USER
                log_callback=lambda msg: asyncio.create_task(
                    context.bot.send_message(chat_id=query.message.chat.id, text=msg)
                ),
                send_pdf_callback=None,
            )

        asyncio.create_task(generate())

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
        return

    if query.data.startswith("pdf_"):
        tp_num = query.data.split("_", 1)[1]
        pdf_path = os.path.join(session["pdf_dir"], f"{tp_num}.pdf")
        if os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                await context.bot.send_document(
                    chat_id=query.message.chat.id,
                    document=f,
                    filename=f"{tp_num}.pdf",
                    caption=f"📎 TP: {tp_num}",
                )
        else:
            await context.bot.send_message(chat_id=query.message.chat.id, text="❌ PDF not found.")
        return


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cleanup_user(update.effective_user.id)
    await update.message.reply_text("🚫 Operation cancelled.")
    return ConversationHandler.END


async def main():
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

    print("🤖 Bot is running...")
    await app.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
