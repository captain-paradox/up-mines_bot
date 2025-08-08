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
from pdf_gen import pdf_gen  # Make sure pdf_gen returns merged path

BOT_TOKEN = '8210338606:AAHP-s930VLar4oIk8M4A4ecGIV-4ZZa7s4'  # 🔐 Replace with your actual bot token

ASK_START, ASK_END, ASK_DISTRICT = range(3)
user_sessions = {}

def start(update: Update, context: CallbackContext):
    update.message.reply_text("Welcome! Please enter the start number:")
    return ASK_START

def ask_start(update: Update, context: CallbackContext):
    try:
        context.user_data['start'] = int(update.message.text)
        update.message.reply_text("Got it. Now enter the end number:")
        return ASK_END
    except ValueError:
        update.message.reply_text("Please enter a valid number.")
        return ASK_START

def ask_end(update: Update, context: CallbackContext):
    try:
        context.user_data['end'] = int(update.message.text)
        update.message.reply_text("Now, please enter the district name:")
        return ASK_DISTRICT
    except ValueError:
        update.message.reply_text("Please enter a district name.")
        return ASK_END

def ask_district(update: Update, context: CallbackContext):
    district = update.message.text
    start = context.user_data['start']
    end = context.user_data['end']
    user_id = update.effective_user.id

    update.message.reply_text(f"Fetching data for district: {district}...")

    user_sessions[user_id] = {"start": start, "end": end, "district": district, "data": []}

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

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

    loop.run_until_complete(run_fetch())

    if user_sessions[user_id]["data"]:
        keyboard = [
            [InlineKeyboardButton("Start Again", callback_data="start_again")],
            [InlineKeyboardButton("Login & Process", callback_data="login_process")],
            [InlineKeyboardButton("Exit", callback_data="exit_process")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text("Data fetched. What would you like to do next?", reply_markup=reply_markup)
    else:
        update.message.reply_text("No data found.")

    return ConversationHandler.END

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    user_id = query.from_user.id

    if query.data == "generate_pdf":
        tp_num_list = context.user_data.get("tp_num_list", [])
        if not tp_num_list:
            query.edit_message_text("⚠️ No TP numbers found. Please process again.")
            return

        async def generate_and_store():
            await pdf_gen(
                tp_num_list,
                log_callback=lambda msg: context.bot.send_message(chat_id=query.message.chat.id, text=msg),
                send_pdf_callback=None  # ❌ Don't send now
            )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(generate_and_store())

        # ✅ Show a button for each PDF
        keyboard = []
        for tp_num in tp_num_list:
            keyboard.append([
                InlineKeyboardButton(f"📄 {tp_num}.pdf", callback_data=f"pdf_{tp_num}")
            ])
        keyboard.append([InlineKeyboardButton("❌ Exit", callback_data="exit_process")])

        context.bot.send_message(
            chat_id=query.message.chat.id,
            text="✅ Click a button below to download:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ✅ Handle individual PDF request buttons
    elif query.data.startswith("pdf_"):
        tp_num = query.data.replace("pdf_", "")
        pdf_path = os.path.join("pdf", f"{tp_num}.pdf")
        if os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                context.bot.send_document(
                    chat_id=query.message.chat.id,
                    document=f,
                    filename=f"{tp_num}.pdf",
                    caption=f"📎 Download PDF for TP {tp_num}"
                )
        else:
            context.bot.send_message(
                chat_id=query.message.chat.id,
                text=f"❌ PDF for TP {tp_num} not found. Please regenerate."
            )
        return

    if user_id not in user_sessions:
        query.edit_message_text("⚠️ Session expired. Please type /start to begin again.")
        return

    session = user_sessions[user_id]

    if query.data == "start_again":
        query.edit_message_text("🔁 Restarting...")
        context.bot.send_message(chat_id=query.message.chat_id, text="/start")
        user_sessions.pop(user_id, None)
        return

    elif query.data == "exit_process":
        query.edit_message_text("❌ Exiting process. Session ended.")
        user_sessions.pop(user_id, None)
        return

    elif query.data == "login_process":
        query.edit_message_text("Processing entries...")

        async def process_and_prompt():
            def log_callback(msg):
                context.bot.send_message(chat_id=query.message.chat.id, text=msg)

            await login_to_website(session["data"], log_callback=log_callback)

            context.user_data["tp_num_list"] = [entry['eMM11_num'] for entry in session["data"]]
            keyboard = [
                [InlineKeyboardButton("📄 Generate PDF", callback_data="generate_pdf")],
                [InlineKeyboardButton("❌ Exit", callback_data="exit_process")],
            ]
            context.bot.send_message(chat_id=query.message.chat.id, text="✅ Click below to generate PDF.",
                                     reply_markup=InlineKeyboardMarkup(keyboard))

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(process_and_prompt())

def cancel(update: Update, context: CallbackContext):
    update.message.reply_text("🚫 Operation cancelled.")
    return ConversationHandler.END

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
