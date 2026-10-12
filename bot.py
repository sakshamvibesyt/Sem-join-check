import os
import secrets
import sqlite3
import threading
import logging
from datetime import datetime, timezone

from flask import Flask
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
)
from telegram.constants import ChatMemberStatus

from web import create_web_app

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("saksham_joingate")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID_RAW = os.getenv("OWNER_ID", "").strip()
OWNER_ID = int(OWNER_ID_RAW) if OWNER_ID_RAW.isdigit() else None
WEB_BASE_URL = os.getenv("WEB_BASE_URL", "").strip().rstrip("/")
GROUP_URL = os.getenv("GROUP_URL", "https://t.me/+FlU57qlj_GVhM2E1").strip()
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@aboutsaksham").strip()
YOUTUBE_URL = os.getenv("YOUTUBE_URL", "https://youtube.com/@sakshamvibesyt").strip()
DB_PATH = os.getenv("DB_PATH", "joingate.db")
PORT = int(os.getenv("PORT", os.getenv("WEB_PORT", "10000")))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Add it in Render Environment Variables.")
if not WEB_BASE_URL.startswith("https://"):
    raise RuntimeError("WEB_BASE_URL must be the public HTTPS URL of this Render service.")

def db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending (
                token TEXT PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS verified (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                verified_at TEXT NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            )
        """)

def create_pending(chat_id: int, user_id: int) -> str:
    token = secrets.token_urlsafe(24)
    with db() as conn:
        conn.execute(
            "INSERT INTO pending(token, chat_id, user_id, created_at) VALUES(?,?,?,?)",
            (token, chat_id, user_id, datetime.now(timezone.utc).isoformat()),
        )
    return token

def get_pending(token: str):
    with db() as conn:
        return conn.execute("SELECT * FROM pending WHERE token=?", (token,)).fetchone()

def delete_pending(token: str):
    with db() as conn:
        conn.execute("DELETE FROM pending WHERE token=?", (token,))

def record_verified(chat_id: int, user_id: int):
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO verified(chat_id,user_id,verified_at) VALUES(?,?,?)",
            (chat_id, user_id, datetime.now(timezone.utc).isoformat()),
        )

def mute_permissions():
    from telegram import ChatPermissions
    return ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
    )

def unmute_permissions():
    from telegram import ChatPermissions
    return ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
        can_add_web_page_previews=True,
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not update.effective_message:
        return

    if context.args and context.args[0].startswith("verify_"):
        token = context.args[0][7:]
        pending = get_pending(token)
        if not pending or int(pending["user_id"]) != user.id:
            await update.effective_message.reply_text(
                "⚠️ This verification link is invalid or expired. Please use the latest link in your group."
            )
            return

        keyboard = [[InlineKeyboardButton(
            "🌐 Open Secure Verification",
            web_app=WebAppInfo(url=f"{WEB_BASE_URL}/?token={token}")
        )]]
        await update.effective_message.reply_text(
            "🔐 SAKSHAM JOINGATE\n\n"
            "1. Open the verification page below.\n"
            "2. Join the required Telegram channel.\n"
            "3. Return to the page and tap “Done — Verify Membership”.\n\n"
            "You will be unmuted in the group after the channel membership is confirmed.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    await update.effective_message.reply_text(
        "👋 Welcome to Saksham JoinGate!\n\n"
        "This bot verifies membership in the required Telegram channel before allowing a new group member to chat.\n"
        "To start, join the group and use the verification button sent there."
    )

async def new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat
    if not message or not chat or not message.new_chat_members:
        return

    for member in message.new_chat_members:
        if member.is_bot:
            continue
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=member.id,
                permissions=mute_permissions(),
            )
        except Exception:
            log.exception("Could not mute new member %s in %s", member.id, chat.id)
            await message.reply_text(
                f"⚠️ I couldn't restrict {member.mention_html()}.\n"
                "Please make sure I am an admin with the permission to restrict members.",
                parse_mode="HTML",
            )
            continue

        token = create_pending(chat.id, member.id)
        try:
            me = await context.bot.get_me()
            deep_link = f"https://t.me/{me.username}?start=verify_{token}"
            keyboard = [[InlineKeyboardButton("🔐 Verify Membership", url=deep_link)]]
            await message.reply_text(
                f"🔐 Welcome, {member.mention_html()}!\n\n"
                "You are temporarily muted until you verify your membership.\n"
                "Tap the button below, open the verification page, and follow the steps.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML",
            )
        except Exception:
            log.exception("Could not send verification message")
            await message.reply_text(
                f"Welcome {member.first_name}! Please contact an admin to complete verification."
            )

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if update.effective_message and user:
        await update.effective_message.reply_text(f"Your Telegram user ID: `{user.id}`", parse_mode="Markdown")

async def owner_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.effective_message
    if not message or not user:
        return
    if OWNER_ID is None or user.id != OWNER_ID:
        await message.reply_text("This command is for the bot owner only.")
        return
    with db() as conn:
        pending_count = conn.execute("SELECT COUNT(*) FROM pending").fetchone()[0]
        verified_count = conn.execute("SELECT COUNT(*) FROM verified").fetchone()[0]
    await message.reply_text(
        "🛠 Saksham JoinGate status\n"
        f"Pending verifications: {pending_count}\n"
        f"Verified records: {verified_count}\n"
        f"Required channel: {CHANNEL_USERNAME}\n"
        f"Owner ID configured: {'Yes' if OWNER_ID else 'No'}"
    )

def main():
    init_db()
    flask_app = create_web_app(
        bot_token=BOT_TOKEN,
        db_path=DB_PATH,
        channel_username=CHANNEL_USERNAME,
        group_url=GROUP_URL,
        youtube_url=YOUTUBE_URL,
    )
    threading.Thread(
        target=lambda: flask_app.run(host="0.0.0.0", port=PORT, threaded=True, use_reloader=False),
        daemon=True,
        name="captcha-web",
    ).start()

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("id", id_command))
    application.add_handler(CommandHandler("status", owner_status))
    application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, new_members))

    log.info("Starting Saksham JoinGate bot and web server on port %s", PORT)
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
