import asyncio
import html
import os
import re
from urllib.parse import urlparse

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
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
            InlineKeyboardButton("📋 SETTINGS", callback_data="settings"),
        ],
        [InlineKeyboardButton("⬅️ BACK", callback_data="back")],
    ])


def settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Schoology URL", callback_data="set:schoology_url")],
        [InlineKeyboardButton("📧 Schoology email", callback_data="set:schoology_user")],
        [InlineKeyboardButton("🔑 Schoology password", callback_data="set:schoology_password")],
        [InlineKeyboardButton("⏰ School time", callback_data="set:school_time")],
        [InlineKeyboardButton("🎥 Zoom time", callback_data="set:zoom_time")],
        [InlineKeyboardButton("📅 School days", callback_data="set:school_days")],
        [InlineKeyboardButton("🔗 Zoom lesson URL", callback_data="set:zoom_url")],
        [InlineKeyboardButton("🌐 Brave path", callback_data="set:browser")],
        [InlineKeyboardButton("📁 Browser profile", callback_data="set:browser_profile")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="school")],
    ])


def url_line(label: str, value: str) -> str:
    value = value.strip()
    if not value:
        return f"{label}: <i>not set</i>"

    safe = html.escape(value, quote=True)
    return f'{label}: <a href="{safe}">{html.escape(value)}</a>'


def day_names(days: list[int]) -> str:
    names = {
        0: "Mon",
        1: "Tue",
        2: "Wed",
        3: "Thu",
        4: "Fri",
        5: "Sat",
        6: "Sun",
    }
    return ", ".join(names.get(day, str(day)) for day in days)


def school_text() -> str:
    s = load_settings()
    status = "🟢 ON" if s["school_enabled"] else "🔴 OFF"

    return (
        f"🎓 <b>School Mode</b> — {status}\n\n"
        f"⏰ School: <b>{html.escape(str(s['school_time']))}</b>\n"
        f"🎥 Zoom: <b>{html.escape(str(s['zoom_time']))}</b>\n"
        f"📅 Days: <b>{html.escape(day_names(s['school_days']))}</b>\n\n"
        f"{url_line('🎥 Lesson', str(s.get('zoom_url', '')))}\n"
        f"{url_line('🌐 Schoology', str(s.get('schoology_url', '')))}"
    )


def settings_text() -> str:
    s = load_settings()
    password_state = "configured" if s["schoology_password"] else "not set"

    return (
        "⚙️ <b>Current settings</b>\n\n"
        f"School Mode: <b>{'ON' if s['school_enabled'] else 'OFF'}</b>\n"
        f"School time: <b>{html.escape(str(s['school_time']))}</b>\n"
        f"Zoom time: <b>{html.escape(str(s['zoom_time']))}</b>\n"
        f"School days: <b>{html.escape(day_names(s['school_days']))}</b>\n"
        f"Schoology email: <code>{html.escape(s['schoology_user'] or 'not set')}</code>\n"
        f"Schoology password: <b>{password_state}</b>\n\n"
        f"{url_line('🎥 Zoom lesson', str(s.get('zoom_url', '')))}\n"
        f"{url_line('🌐 Schoology', str(s.get('schoology_url', '')))}\n\n"
        f"🌐 Brave: <code>{html.escape(str(s['browser']))}</code>\n"
        f"📁 Profile: <code>{html.escape(str(s['browser_profile']))}</code>"
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

    if key == "school_days":
        try:
            days = sorted(set(int(item.strip()) for item in value.split(",")))
        except ValueError:
            days = []

        if not days or any(day < 0 or day > 6 for day in days):
            context.user_data[PENDING_KEY] = key
            await update.message.reply_text(
                "Use numbers 0-6 separated by commas. Example: 0,1,2,3,4 for Monday-Friday."
            )
            return

        value = days

    if key in {"school_time", "zoom_time"} and not valid_time(value):
        context.user_data[PENDING_KEY] = key
        await update.message.reply_text("Use HH:MM, for example 08:30.")
        return

    if key == "schoology_url" and not valid_url(value):
        context.user_data[PENDING_KEY] = key
        await update.message.reply_text("Send a valid http/https Schoology Student Login URL.")
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
        if data in {"school", "view_settings"}:
            await query.edit_message_text(
                school_text(),
                parse_mode=ParseMode.HTML,
                reply_markup=school_keyboard(),
                disable_web_page_preview=True,
            )
            return

        if data == "settings":
            await query.edit_message_text(
                settings_text(),
                parse_mode=ParseMode.HTML,
                reply_markup=settings_keyboard(),
                disable_web_page_preview=True,
            )
            return

        if data == "toggle_school":
            settings = load_settings()
            settings["school_enabled"] = not settings["school_enabled"]
            save_settings(settings)
            await query.edit_message_text(
                school_text(),
                parse_mode=ParseMode.HTML,
                reply_markup=school_keyboard(),
                disable_web_page_preview=True,
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
                "schoology_url": "Send the Schoology Student Login URL.",
                "schoology_user": "Send the Schoology email/username.",
                "schoology_password": "Send the Schoology password. It will be stored locally and the incoming message will be deleted when possible.",
                "school_time": "Send the school start time as HH:MM, e.g. 08:20.",
                "zoom_time": "Send the Zoom time as HH:MM, e.g. 08:30.",
                "school_days": "Send days as numbers 0-6. Example: 0,1,2,3,4 for Monday-Friday.",
                "zoom_url": "Send the full Zoom lesson URL.",
                "browser": "Send the Brave executable path, e.g. /usr/bin/brave.",
                "browser_profile": "Send the Brave browser profile path.",
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
                f"Host: {html.escape(result['hostname'])}\n"
                f"School Mode: {'ON' if settings['school_enabled'] else 'OFF'}\n\n"
                f"{url_line('🎥 Lesson', str(settings.get('zoom_url', '')))}"
            )
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=main_keyboard(),
                disable_web_page_preview=True,
            )
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

        await query.edit_message_text(
            "Unknown action.",
            reply_markup=main_keyboard(),
        )

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
