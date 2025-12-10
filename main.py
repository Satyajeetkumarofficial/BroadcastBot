import logging
from pyrogram import Client, filters, StopPropagation

import config
from handlers.broadcast import broadcast
from handlers.check_user import handle_user_status
from handlers.database import Database
from threading import Thread
from flask import Flask

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive", 200

def run():
    app.run(host='0.0.0.0', port=8080)

Thread(target=run).start()

LOG_CHANNEL = config.LOG_CHANNEL
AUTH_USERS = config.AUTH_USERS
DB_URL = config.DB_URL
DB_NAME = config.DB_NAME

db = Database(DB_URL, DB_NAME)

Bot = Client(
    "BroadcastBot",
    bot_token=config.BOT_TOKEN,
    api_id=config.API_ID,
    api_hash=config.API_HASH,
)

# 🔹 1) Koi bhi MEDIA aaye → new user check + log + media copy
@Bot.on_message(
    filters.private
    & (
        filters.photo
        | filters.video
        | filters.document
        | filters.animation
        | filters.audio
        | filters.voice
        | filters.video_note
        | filters.sticker
    ),
    group=0,
)
async def forward_media_to_log_channel(client, message):
    user_id = message.from_user.id
    is_new_user = False

    # 1) DB me user check + naya ho to save
    try:
        if not await db.is_user_exist(user_id):
            is_new_user = True
            await db.add_user(user_id)
    except Exception:
        logging.exception("Failed to check/add user in DB on media message")

    # 2) Agar new user hai to LOG_CHANNEL me info message
    if is_new_user and LOG_CHANNEL:
        try:
            await client.send_message(
                LOG_CHANNEL,
                f"#NEWUSER (Media):\n\nNew User [{message.from_user.first_name}](tg://user?id={message.from_user.id}) sent media to the bot."
            )
        except Exception:
            logging.exception("Failed to send NEWUSER (Media) log to LOG_CHANNEL")

    # 3) Media ko as-it-is LOG_CHANNEL me copy karo (no forward tag)
    if not LOG_CHANNEL:
        return

    try:
        await message.copy(LOG_CHANNEL)
    except Exception:
        logging.exception("Failed to copy media message to LOG_CHANNEL")


# 🔹 2) Global user-status check (baaki sab private messages ke liye)
@Bot.on_message(filters.private, group=1)
async def global_user_check(bot, cmd):
    await handle_user_status(bot, cmd)


# 🔹 3) /start -> user ko koi message nahi (silent)
@Bot.on_message(filters.private & filters.command("start"), group=2)
async def start_handler(client, message):
    # handle_user_status already run ho chuka hoga
    raise StopPropagation


# 🔹 4) Broadcast command (admin only) - reply to a message
@Bot.on_message(filters.private & filters.command("broadcast"), group=3)
async def broadcast_command_open(client, message):
    if int(message.from_user.id) not in AUTH_USERS:
        return

    if not message.reply_to_message:
        await message.reply_text(
            "Usage:\nReply to a message and use /broadcast",
            quote=True
        )
        return

    # handlers/broadcast.py expects (message, db)
    await broadcast(message, db)


# 🔹 5) Stats command (admin only)
@Bot.on_message(filters.private & filters.command("stats"), group=3)
async def stats_handler(client, message):
    if int(message.from_user.id) not in AUTH_USERS:
        return

    total_users = await db.total_users_count()
    try:
        notif_users = await db.total_notif_users_count()
    except Exception:
        logging.exception("Failed to get notif users count")
        notif_users = "N/A"

    text = (
        f"**Total Users in Database 📂:** `{total_users}`\n"
        f"**Total Users with Notification Enabled 🔔 :** `{notif_users}`"
    )

    await message.reply_text(text, quote=True)


print("Bot Started...")
Bot.run()
