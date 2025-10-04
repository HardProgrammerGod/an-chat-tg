import asyncio
import os
import time
import logging
from typing import Dict, List, Tuple
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
import database
from aiohttp import web

# --- Initialization ---
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID") or 0)

if not BOT_TOKEN or not ADMIN_ID:
    raise RuntimeError("BOT_TOKEN or ADMIN_ID not set in .env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Initialize DB
database.init_db()

# --- Last messages (for reports) ---
last_messages: Dict[int, List[Tuple[int, int]]] = {}

def push_last_message(user_id: int, chat_id: int, message_id: int, limit: int = 5):
    lst = last_messages.get(user_id, [])
    lst.append((chat_id, message_id))
    if len(lst) > limit:
        lst = lst[-limit:]
    last_messages[user_id] = lst

async def notify_user(user_id: int, text: str):
    try:
        await bot.send_message(user_id, text)
    except Exception as e:
        logger.warning(f"Failed to send message to {user_id}: {e}")

# --- Rate limiting ---
last_action_time: Dict[str, float] = {}

def is_rate_limited(user_id: int, action: str, cooldown: int) -> bool:
    now = time.time()
    key = f"{user_id}:{action}"
    last_time = last_action_time.get(key, 0)
    if now - last_time < cooldown:
        return True
    last_action_time[key] = now
    return False

# --- Limits Settings ---
CHANNEL = "@nedo_dev"
LIMIT = 5
RESET_SECONDS = 3600

# --- Check subscription ---
async def is_subscribed(user_id: int, channel_username: str) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=channel_username, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception:
        return False

# --- Commands ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = message.from_user
    database.add_user(user.id, user.username, user.first_name, user.last_name)
    if database.is_blocked(user.id):
        await message.answer("You are blocked and cannot use the bot.")
        return
    await message.answer("👋 Welcome! Use /next to find a chat partner.\nType /commands to see all available commands.")

@dp.message(Command("commands"))
async def show_commands(message: Message):
    commands_text = (
        "📖 Available commands:\n"
        "/start - Start the bot\n"
        "/next - Find a chat partner\n"
        "/stop - End the chat\n"
        "/report - Report your partner to admin\n"
        "/commands - Show this list of commands"
    )
    await message.answer(commands_text)

@dp.message(Command("next"))
async def cmd_next(message: Message):
    user = message.from_user
    uid = user.id

    if is_rate_limited(uid, "next", cooldown=5):
        await message.answer("⏳ Please wait a few seconds before using /next again.")
        return

    database.add_user(uid, user.username, user.first_name, user.last_name)

    if database.is_blocked(uid):
        await message.answer("You are blocked and cannot use this feature.")
        return

    info = database.get_limit_info(uid)
    used, reset_time, premium = info["used_count"], info["reset_time"], info["premium"]

    now = int(time.time())
    if now > reset_time:
        used, reset_time = 0, now + RESET_SECONDS

    if not premium:
        if used >= LIMIT:
            if await is_subscribed(uid, CHANNEL):
                premium = 1
                await message.answer("✅ You are subscribed to our channel! The limit has been completely removed. 🚀")
            else:
                await message.answer(
                    f"⛔ You have used {LIMIT} searches this hour.\n\n"
                    f"👉 Subscribe to our channel to remove the limit: {CHANNEL}"
                )
                database.update_limit(uid, used, reset_time, premium)
                return

    if not premium:
        used += 1

    database.update_limit(uid, used, reset_time, premium)

    partner = database.get_partner(uid)
    if partner:
        database.remove_chat_by_users(uid, partner)
        await notify_user(partner, "🔴 Your partner has left the chat.")
        await message.answer("🔴 You left the chat. Searching for a new partner...")

    candidate = database.get_first_in_queue(exclude_user_id=uid)
    if candidate:
        database.remove_from_queue(candidate)
        database.add_chat(uid, candidate)
        await notify_user(candidate, "🔗 Partner found! Type /commands to see options.")
        await message.answer("🔗 Partner found! Type /commands to see options.")
    else:
        database.add_to_queue(uid)
        await message.answer(
            "⏳ You have been added to the queue. Please wait for a partner.\n\n"
            "Available commands:\n"
            "/stop - leave the queue\n"
            "/report - report your partner\n"
            "/next - find a new partner\n"
            "/commands - show all commands"
        )

@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    uid = message.from_user.id
    partner = database.get_partner(uid)
    if partner:
        database.remove_chat_by_users(uid, partner)
        await notify_user(partner, "🔴 Your partner ended the chat (/stop).")
        await message.answer("🔴 You ended the chat.\n\nType /commands to see available options.")
    else:
        database.remove_from_queue(uid)
        await message.answer("You are not in a chat. If you were in the queue, you have been removed.\n\nType /commands to see available options.")

@dp.message(Command("report"))
async def cmd_report(message: Message):
    reporter = message.from_user.id
    partner = database.get_partner(reporter)
    if not partner:
        await message.answer("You are not in a chat, nothing to report.")
        return

    database.add_report(reporter, partner)
    await message.answer("✅ Report sent to admin. Thank you!")

    msgs = last_messages.get(partner, [])
    if not msgs:
        await bot.send_message(ADMIN_ID, f"Report from {reporter} about {partner}. No messages found.")
        return

    await bot.send_message(ADMIN_ID, f"📣 Report from {reporter} about {partner}. Last partner messages (up to 5):")
    for (from_chat_id, message_id) in msgs:
        try:
            await bot.copy_message(chat_id=ADMIN_ID, from_chat_id=from_chat_id, message_id=message_id)
        except Exception as e:
            logger.warning(f"Failed to copy message {message_id} from {from_chat_id} to admin: {e}")
    await bot.send_message(ADMIN_ID, f"End of report. Reporter: {reporter}, Reported: {partner}")

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("This command is only available to the admin.")
        return
    stats = database.get_stats()
    text = (
        f"📊 Stats:\n"
        f"- Users in DB: {stats['users']}\n"
        f"- Active chats: {stats['active_chats']}\n"
        f"- Reports: {stats['reports']}\n"
        f"- In queue: {stats['queue']}\n"
    )
    await message.answer(text)

@dp.message(Command("block"))
async def cmd_block(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Only the admin can block users.")
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Usage: /block <user_id>")
        return
    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("Invalid user_id.")
        return
    database.block_user(user_id)
    partner = database.get_partner(user_id)
    if partner:
        database.remove_chat_by_users(user_id, partner)
        await notify_user(partner, "🔴 Your partner was blocked by the admin.")
    database.remove_from_queue(user_id)
    await notify_user(user_id, "You have been blocked. You cannot use the bot.")
    await message.answer(f"User {user_id} blocked.")

@dp.message(Command("unblock"))
async def cmd_unblock(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Only the admin can unblock users.")
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Usage: /unblock <user_id>")
        return
    try:
        user_id = int(parts[1])
    except ValueError:
        await message.answer("Invalid user_id.")
        return
    database.unblock_user(user_id)
    await notify_user(user_id, "You have been unblocked. You can use the bot again.")
    await message.answer(f"User {user_id} unblocked.")

# --- Forward only text ---
@dp.message(F.text & ~F.text.startswith("/"))
async def handle_text(message: Message):
    uid = message.from_user.id
    if database.is_blocked(uid):
        return

    partner_id = database.get_partner(uid)
    if not partner_id:
        await message.answer("❗ You do not have an active conversation partner. Use /next.")
        return

    push_last_message(uid, message.chat.id, message.message_id, limit=5)

    try:
        await bot.send_message(partner_id, message.text)
    except Exception as e:
        logger.warning(f"Failed to send text to {partner_id}: {e}")
        await message.answer("Failed to deliver the message.")

# --- Block all media ---
@dp.message(F.content_type.in_({"photo", "video", "voice", "audio", "sticker", "document"}))
async def block_media(message: Message):
    await message.answer("🚫 Only text messages are allowed.")

# --- Startup/Shutdown ---
async def on_startup():
    logger.info("Bot started")

async def on_shutdown():
    await bot.session.close()
    logger.info("Bot stopped")

# --- Minimal web server for Render ---
async def handle(request):
    return web.Response(text="OK")

app = web.Application()
app.add_routes([web.get("/", handle)])

async def start_web_server():
    port = int(os.environ.get("PORT", 8000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web server running on port {port}")

# --- Main ---
async def main():
    await start_web_server()
    loop = asyncio.get_event_loop()
    loop.create_task(dp.start_polling(bot, on_startup=on_startup, on_shutdown=on_shutdown))
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
