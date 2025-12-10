import os
import traceback
import logging

from pyrogram import Client
from pyrogram import StopPropagation, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

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


# Global user status checker (ban / etc)
@Bot.on_message(filters.private)
async def _(bot, cmd):
    await handle_user_status(bot, cmd)


# /start -> sirf DB me save kare, user ko koi msg nahi
@Bot.on_message(filters.command("start") & filters.private)
async def startprivate(client, message):
    chat_id = message.from_user.id
    # Save user in database if not exists
    if not await db.is_user_exist(chat_id):
        data = await client.get_me()
        BOT_USERNAME = data.username
        await db.add_user(chat_id)
        if LOG_CHANNEL:
            try:
                await client.send_message(
                    LOG_CHANNEL,
                    f"#NEWUSER:\n\nNew User [{message.from_user.first_name}](tg://user?id={message.from_user.id}) started @{BOT_USERNAME}"
                )
            except Exception:
                logging.exception("Failed to send new user log to LOG_CHANNEL")
        else:
            logging.info(
                f"#NewUser :- Name : {message.from_user.first_name} ID : {message.from_user.id}"
            )

    # User ko koi reply nahi
    raise StopPropagation


# 👉 Koi bhi media aaye: pehle user ko DB me save karo (agar new hai),
# new user ho to log channel me message bhejo,
# fir same media LOG_CHANNEL me copy karo (no forward tag, no change)
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
    )
)
async def forward_media_to_log_channel(client, message):
    """Every private media message:
       1) ensure user is saved in DB
       2) if new user -> send new user log to LOG_CHANNEL
       3) copy media to LOG_CHANNEL without modification
    """
    user_id = message.from_user.id
    is_new_user = False

    # 1) Agar user DB me nahi hai to new user ke रूप में save karo
    try:
        if not await db.is_user_exist(user_id):
            is_new_user = True
            await db.add_user(user_id)
    except Exception:
        logging.exception("Failed to check/add user in DB on media message")

    # 2) Agar new user hai to log channel me "new user" message bhejo
    if is_new_user and LOG_CHANNEL:
        try:
            # yaha simple new user log bhej rahe hain (media se joined)
            await client.send_message(
                LOG_CHANNEL,
                f"#NEWUSER (Media):\n\nNew User [{message.from_user.first_name}](tg://user?id={message.from_user.id}) sent media to the bot."
            )
        except Exception:
            logging.exception("Failed to send new user (media) log to LOG_CHANNEL")

    # 3) Media ko LOG_CHANNEL me as-it-is copy karo
    if not LOG_CHANNEL:
        return

    try:
        # copy() -> same media + same caption, without 'forwarded from' tag
        await message.copy(LOG_CHANNEL)
    except Exception:
        logging.exception("Failed to copy media message to LOG_CHANNEL")


@Bot.on_message(filters.command("settings") & filters.private)
async def opensettings(client, message):
    user_id = message.from_user.id
    if not await db.is_user_exist(user_id):
        await db.add_user(user_id)

    notif = await db.get_notif(user_id)

    inline_keyboard = [[InlineKeyboardButton(
        f"NOTIFICATION  {'🔔' if (notif is True) else '🔕'}",
        callback_data="notifon"
    )],
        [InlineKeyboardButton("❎", callback_data="closeMeh")]]

    reply_markup = InlineKeyboardMarkup(inline_keyboard)

    await message.reply_text(
        f"**Here You Can Set Your Settings:**\n\n**Notification** : `{notif}`",
        reply_markup=reply_markup
    )
    raise StopPropagation


@Bot.on_message(filters.private & filters.command("broadcast"))
async def broadcast_command_open(client, message):
    """Send broadcast command"""
    if int(message.from_user.id) not in AUTH_USERS:
        return

    if not message.reply_to_message:
        await message.reply_text("Usage:\nReply to a message and use /broadcast", quote=True)
        return

    await broadcast(client, message)


@Bot.on_message(filters.private & filters.command("stats"))
async def stats_handler(_, message):
    if int(message.from_user.id) not in AUTH_USERS:
        return
    
    total_users = await db.total_users_count()
    banned_users = await db.banned_users_count()
    notif = await db.get_notif(message.from_user.id)

    text = f"**Total Users in DB:** `{total_users}`\n"
    text += f"**Total Banned Users:** `{banned_users}`\n"
    text += f"**Your Notification Setting:** `{notif}`"

    await message.reply_text(text, quote=True)


@Bot.on_message(filters.private & filters.command("ban_user"))
async def ban_user_handler(_, message):
    if int(message.from_user.id) not in AUTH_USERS:
        return

    if len(message.command) != 2:
        await message.reply_text("Usage:\n/ban_user user_id", quote=True)
        return

    user_id = int(message.command[1])
    if user_id == message.from_user.id:
        await message.reply_text("You can't ban yourself!", quote=True)
        return

    if await db.is_user_exist(user_id):
        await db.ban_user(user_id)
        await message.reply_text(f"User {user_id} has been banned.", quote=True)
    else:
        await message.reply_text("User not found in database.", quote=True)


@Bot.on_message(filters.private & filters.command("unban_user"))
async def unban_user_handler(_, message):
    if int(message.from_user.id) not in AUTH_USERS:
        return

    if len(message.command) != 2:
        await message.reply_text("Usage:\n/unban_user user_id", quote=True)
        return

    user_id = int(message.command[1])

    if await db.is_user_exist(user_id):
        await db.remove_ban(user_id)
        await message.reply_text(f"User {user_id} has been unbanned.", quote=True)
    else:
        await message.reply_text("User not found in database.", quote=True)


@Bot.on_message(filters.private & filters.command("banned_users"))
async def banned_users_handler(_, message):
    if int(message.from_user.id) not in AUTH_USERS:
        return

    banned_users = await db.get_banned_users()
    if not banned_users:
        await message.reply_text("No banned users found.", quote=True)
        return

    text = "**Banned Users:**\n"
    for user in banned_users:
        text += f"`{user['user_id']}`\n"

    await message.reply_text(text, quote=True)


@Bot.on_callback_query()
async def callback_query_handler(client: Client, cb: CallbackQuery):
    user_id = cb.from_user.id
    if cb.data == "notifon":
        if await db.get_notif(user_id) is True:
            await db.set_notif(user_id, False)
        else:
            await db.set_notif(user_id, True)

        await cb.message.edit(
            f"`Here You Can Set Your Settings:`\n\nSuccessfully setted notifications to **{await db.get_notif(user_id)}**",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            f"NOTIFICATION  {'🔔' if ((await db.get_notif(user_id)) is True) else '🔕'}",
                            callback_data="notifon",
                        )
                    ],
                    [InlineKeyboardButton("❎", callback_data="closeMeh")],
                ]
            ),
        )
        await cb.answer(
            f"Successfully setted notifications to {await db.get_notif(user_id)}"
        )
    else:
        await cb.message.delete(True)

print("Bot Started...")
Bot.run()
