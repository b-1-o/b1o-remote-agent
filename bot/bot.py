import asyncio
import os
import re
from urllib.parse import urlparse

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from automation.school import open_school_session
from config_store import load_settings, save_settings

AGENT_URL = os.getenv("B1O_AGENT_URL", "http://127.0.0.1:8765")
AGENT_TOKEN = os.getenv("B1O_REMOTE_TOKEN", "")
TELEGRAM_TOKEN = os.getenv("B1O_TELEGRAM_TOKEN", "")
ALLOWED_CHAT_ID = os.getenv("B1O_TELEGRAM_CHAT_ID", "")

PENDING_KEY = "pending_setting"


def allowed(update: Update) -> bool:
    return (
        bool(ALLOWED_CHAT_ID)
        and update.effective_chat is not None
        and str(update.effective_chat.id) == ALLOWED_CHAT_ID
    )


async def agent_request(method: str, path: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.request(
            method,
            f"{AGENT_URL}{path}",
            headers={"X-Agent-Token": AGENT_TOKEN},
        )
        response.raise_for_status()
        return response.json()


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎓 SCHOOL MODE", callback_data="school")],
        [InlineKeyboardButton("⚙️ SETTINGS", callback_data="settings")],
        [InlineKeyboardButton("📊 STATUS", callback_data="status")],
        [InlineKeyboardButton("🔒 LOCK", callback_data="lock")],
        [InlineKeyboardButton("⏻ SHUTDOWN", callback_data="shutdown")],
    ])


def school_keyboard() -> InlineKeyboardMarkup:
    settings = load_settings()
    state = "🟢 ON" if settings["school_enabled"] else "🔴 OFF"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"School Mode: {state}", callback_data="toggle_school")],
        [
            InlineKeyboardButton("▶️ RUN NOW", callback_data="run_school"),
            InlineKeyboardButton("📋 VIEW", callback_data="view_settings"),
        ],
        [InlineKeyboardButton("⚙️ EDIT SETTINGS", callback_data="settings")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="back")],
    ])


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📧 Schoology email", callback_data="set:schoology_user")],
        [InlineKeyboardButton("🔑 Schoology password", callback_data="set:schoology_password")],
        [InlineKeyboardButton("⏰ School time", callback_data="set:school_time")],
        [InlineKeyboardButton("🎥 Zoom time", callback_data="set:zoom_time")],
        [InlineKeyboardButton("🔗 Zoom URL", callback_data="set:zoom_url")],
        [InlineKeyboardButton("🌐 Browser", callback_data="set:browser")],
        [InlineKeyboardButton("📁 Browser profile", callback_data="set:browser_profile")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="school")],
    ])


def settings_text() -> str:
    s = load_settings()
    password_state = "configured" if s["schoology_password"] else "not set"

    return (
        "⚙️ Current settings\n\n"
        f"School Mode: {'ON' if s['school_enabled'] else 'OFF'}\n"
        f"School time: {s['school_time']}\n"
        f"Zoom time: {s['zoom_time']}\n"
        f"Schoology email: {s['schoology_user'] or 'not set'}\n"
        f"Schoology password: {password_state}\n"
        f"Zoom URL: {'configured' if s['zoom_url'] else 'not set'}\n"
        f"Browser: {s['browser']}\n"
        f"Profile: {s['browser_profile']}"
    )


def valid_time(value: str) -> bool:
    return bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value.strip()))


def valid_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    await update.message.reply_text(
        "b1o Remote\n\nChoose an action:",
        reply_markup=main_keyboard(),
    )


async def handle_setting_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return

    key = context.user_data.pop(PENDING_KEY, None)
    if not key:
        return

    value = update.message.text.strip()

    if key in {"school_time", "zoom_time"} and not valid_time(value):
        context.user_data[PENDING_KEY] = key
        await update.message.reply_text(
            "Use HH:MM, for example 08:30.",
        )
        return

    if key == "zoom_url" and not valid_url(value):
        context.user_data[PENDING_KEY] = key
        await update.message.reply_text("Send a valid http/https Zoom URL.")
        return

    if key == "browser" and not value.startswith("/"):
        context.user_data[PENDING_KEY] = key
        await update.message.reply_text(
            "Send the absolute Brave executable path, e.g. /usr/bin/brave."
        )
        return

    if key == "browser_profile" and not value:
        context.user_data[PENDING_KEY] = key
        await update.message.reply_text("Send the browser profile path.")
        return

    settings = load_settings()
    settings[key] = value
    save_settings(settings)

    # Password messages should not remain in the Telegram chat if deletion
    # is permitted for this private bot chat.
    if key == "schoology_password":
        try:
            await update.message.delete()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🔑 Schoology password saved locally.",
        )
    else:
        await update.message.reply_text(
            f"✅ {key.replace('_', ' ').title()} updated.",
            reply_markup=settings_keyboard(),
        )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not allowed(update):
        return

    data = query.data or ""

    try:
        if data == "school":
            await query.edit_message_text(
                "🎓 School Mode",
                reply_markup=school_keyboard(),
            )
            return

        if data == "settings":
            await query.edit_message_text(
                settings_text(),
                reply_markup=settings_keyboard(),
            )
            return

        if data == "view_settings":
            await query.edit_message_text(
                settings_text(),
                reply_markup=school_keyboard(),
            )
            return

        if data == "toggle_school":
            settings = load_settings()
            settings["school_enabled"] = not settings["school_enabled"]
            save_settings(settings)
            await query.edit_message_text(
                "🎓 School Mode",
                reply_markup=school_keyboard(),
            )
            return

        if data == "run_school":
            await query.edit_message_text(
                "🚀 Starting School Mode in Brave...",
                reply_markup=school_keyboard(),
            )
            context.application.create_task(
                asyncio.to_thread(open_school_session)
            )
            return

        if data.startswith("set:"):
            key = data.split(":", 1)[1]
            prompts = {
                "schoology_user": "Send the Schoology email/username.",
                "schoology_password": "Send the Schoology password. It will be stored locally and the incoming message will be deleted when possible.",
                "school_time": "Send the school start time as HH:MM, e.g. 08:20.",
                "zoom_time": "Send the Zoom time as HH:MM, e.g. 08:30.",
                "zoom_url": "Send the full Zoom URL.",
                "browser": "Send the Brave executable path, e.g. /usr/bin/brave.",
                "browser_profile": "Send the Brave automation profile path.",
            }
            prompt = prompts.get(key)
            if not prompt:
                await query.edit_message_text("Unknown setting.")
                return

            context.user_data[PENDING_KEY] = key
            await query.edit_message_text(prompt)
            return

        if data == "status":
            result = await agent_request("GET", "/status")
            settings = load_settings()
            text = (
                f"🟢 Online\n"
                f"Host: {result['hostname']}\n"
                f"School Mode: {'ON' if settings['school_enabled'] else 'OFF'}"
            )
            await query.edit_message_text(text, reply_markup=main_keyboard())
            return

        if data == "lock":
            await agent_request("POST", "/lock")
            await query.edit_message_text(
                "🔒 PC locked.",
                reply_markup=main_keyboard(),
            )
            return

        if data == "shutdown":
            await agent_request("POST", "/shutdown")
            await query.edit_message_text(
                "⏻ Shutdown requested.",
                reply_markup=main_keyboard(),
            )
            return

        if data == "back":
            await query.edit_message_text(
                "b1o Remote\n\nChoose an action:",
                reply_markup=main_keyboard(),
            )
            return

        await query.edit_message_text("Unknown action.", reply_markup=main_keyboard())

    except Exception as exc:
        await query.edit_message_text(
            f"❌ Error: {type(exc).__name__}",
            reply_markup=main_keyboard(),
        )


def main() -> None:
    if not TELEGRAM_TOKEN:
        raise RuntimeError("B1O_TELEGRAM_TOKEN is not configured")
    if not AGENT_TOKEN:
        raise RuntimeError("B1O_REMOTE_TOKEN is not configured")
    if not ALLOWED_CHAT_ID:
        raise RuntimeError("B1O_TELEGRAM_CHAT_ID is not configured")

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_setting_value)
    )
    app.run_polling()


if __name__ == "__main__":
    main()
