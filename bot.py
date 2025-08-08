import os
import asyncio
import shutil

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackQueryHandler,
    CallbackContext,
    ConversationHandler,
)

from fetch_emm11_data import fetch_emm11_data
from login_to_website import login_to_website
from pdf_gen import pdf_gen

BOT_TOKEN = '8210338606:AAHP-s930VLar4oIk8M4A4ecGIV-4ZZa7s4'

ASK_START, ASK_END, ASK_DISTRICT = range(3)

# Stores user sessions: {user_id: {start, end, district, data, tp_num_list}}
user_sessions = {}

# Start command handler
def start(update: Update, context: CallbackContext):
    update.message.reply_text("Welcome! Please enter the start number:")
    return ASK_START

# Ask for start number
def ask_start(update: Update, context: CallbackContext):
    try:
        start = int(update.message.text)
        context.user_data['start'] = start
        update.message.reply_text("Got it. Now enter the end number:")
        return ASK_END
    except ValueError:
        update.message.reply_text("⚠️ Please enter a valid number.")
        return ASK_START

# Ask for end number
def ask_end(update: Update, context: CallbackContext):
    try:
        end = int(update.message.text)
        context.user_data['end'] = end
        update.message.reply_text("Now, please enter the district name:")
        return ASK_DISTRICT
    except ValueError:
        update.message.reply_text("⚠️ Please enter a valid number.")
        return ASK_END

# Ask for district and start fetching data
def ask_district(update: Update, context: CallbackContext):
    district = update.message.text
    user_id = update.effective_user.id
    start = context.user_data['start']
    end = context.user_data['end']

    # Initialize session for user
    user_sessions[user_id] = {
        "start": start,
        "end": end,
        "district": district,
        "data": [],
        "tp_num_list": [],
    }

    update.message.reply_text(f"🔎 Fetching data for district: {district}...")

    # Async fetching with callback
    async def send_entry(entry):
        msg = (
            f"{entry['eMM11_num']}\n"
            f"{entry['destination_district']}\n"
            f"{entry['destination_address']}\n"
            f"{entry['quantity_to_transport']}\n"
            f"{entry['generated_on']}"
        )
        context.bot.send_message(chat_id=update.effective_chat.id, text=msg)
        user_sessions[user_id]["data"].append(entry)

    async def run_fetch():
        await fetch_emm11_data(start, end, district, data_callback=send_entry)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_fetch())

    # If data found, show options
    if user_sessions[user_id]["data"]:
        keyboard = [
            [InlineKeyboardButton("🔁 Start Again", callback_data="start_again")],
            [InlineKeyboardButton("🔐 Login & Process", callback_data="login_process")],
            [InlineKeyboardButton("❌ Exit", callback_data="exit_process")],
        ]
        update.message.reply_text(
            "✅ Data fetched. What would you like to do next?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    else:
        update.message.reply_text("⚠️ No data found.")
        user_sessions.pop(user_id, None)

    return ConversationHandler.END

# Button click handler
def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    query.answer()

    if user_id not in user_sessions:
        query.edit_message_text("⚠️ Session expired. Please start again with /start.")
        return

    session = user_sessions[user_id]

    # Restart
    if query.data == "start_again":
        query.edit_message_text("🔁 Restarting...")
        context.bot.send_message(chat_id=query.message.chat.id, text="/start")
        user_sessions.pop(user_id, None)
        return

    # Exit
    if query.data == "exit_process":
        query.edit_message_text("❌ Exiting session.")
        user_sessions.pop(user_id, None)
        return

    # Login & process
    if query.data == "login_process":
        query.edit_message_text("🔐 Logging in and processing data...")

        async def process_data():
            def log_callback(msg):
                context.bot.send_message(chat_id=query.message.chat.id, text=msg)

            await login_to_website(session["data"], log_callback=log_callback)

            # Save TP numbers
            tp_list = [entry['eMM11_num'] for entry in session["data"]]
            session["tp_num_list"] = tp_list

            # Prompt for PDF generation
            keyboard = [
                [InlineKeyboardButton("📄 Generate PDF", callback_data="generate_pdf")],
                [InlineKeyboardButton("❌ Exit", callback_data="exit_process")]
            ]
            context.bot.send_message(
                chat_id=query.message.chat.id,
                text="✅ Processing done. Click below to generate PDF.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(process_data())
        return

    # Generate PDFs
    if query.data == "generate_pdf":
        tp_list = session.get("tp_num_list", [])
        if not tp_list:
            context.bot.send_message(chat_id=query.message.chat.id, text="⚠️ No TP numbers found.")
            return

        async def generate():
            await pdf_gen(
                tp_list,
                log_callback=lambda msg: context.bot.send_message(chat_id=query.message.chat.id, text=msg),
                send_pdf_callback=None
            )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(generate())

        keyboard = [
            [InlineKeyboardButton(f"📎 {tp}.pdf", callback_data=f"pdf_{tp}")]
            for tp in tp_list
        ]
        keyboard.append([InlineKeyboardButton("❌ Exit", callback_data="exit_process")])

        context.bot.send_message(
            chat_id=query.message.chat.id,
            text="📄 Click to download your PDFs:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # Individual PDF
    if query.data.startswith("pdf_"):
        tp_num = query.data.split("_", 1)[1]
        pdf_path = os.path.join("pdf", f"{tp_num}.pdf")
        if os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                context.bot.send_document(
                    chat_id=query.message.chat.id,
                    document=f,
                    filename=f"{tp_num}.pdf",
                    caption=f"📎 TP: {tp_num}"
                )
        else:
            context.bot.send_message(chat_id=query.message.chat.id, text="❌ PDF not found.")
        return

# Cancel command
def cancel(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    user_sessions.pop(user_id, None)
    update.message.reply_text("🚫 Operation cancelled.")
    return ConversationHandler.END

# Main bot launcher
def main():
    try:
        shutil.rmtree("pdf")
    except:
        pass

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_START: [MessageHandler(Filters.text & ~Filters.command, ask_start)],
            ASK_END: [MessageHandler(Filters.text & ~Filters.command, ask_end)],
            ASK_DISTRICT: [MessageHandler(Filters.text & ~Filters.command, ask_district)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    dp.add_handler(conv_handler)
    dp.add_handler(CallbackQueryHandler(button_handler))

    print("🤖 Bot is running...")
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
