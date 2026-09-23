import asyncio
import html
import os
import re
from pathlib import Path
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
from commands_store import install_pack, load_commands
from config_store import load_settings, save_settings

AGENT_URL = os.getenv("B1O_AGENT_URL", "http://127.0.0.1:8765")
AGENT_TOKEN = os.getenv("B1O_REMOTE_TOKEN", "")
TELEGRAM_TOKEN = os.getenv("B1O_TELEGRAM_TOKEN", "")
ALLOWED_CHAT_ID = os.getenv("B1O_TELEGRAM_CHAT_ID", "")

PENDING_KEY = "pending"
PANEL_KEY = "panel_message_id"


def allowed(update: Update) -> bool:
    return (
        bool(ALLOWED_CHAT_ID)
        and update.effective_chat is not None
        and str(update.effective_chat.id) == ALLOWED_CHAT_ID
    )


async def agent_request(method: str, path: str, json: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.request(
            method,
            f"{AGENT_URL}{path}",
            headers={"X-Agent-Token": AGENT_TOKEN},
            json=json,
        )
        response.raise_for_status()
        return response.json()


async def delete_message(message) -> None:
    try:
        await message.delete()
    except Exception:
        pass


async def save_panel(context: ContextTypes.DEFAULT_TYPE, message) -> None:
    context.chat_data[PANEL_KEY] = message.message_id


async def replace_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> None:
    message = update.callback_query.message if update.callback_query else None

    if message is not None:
        try:
            await message.edit_text(
                text,
                reply_markup=keyboard,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            await save_panel(context, message)
            return
        except Exception:
            pass

    chat_id = update.effective_chat.id
    old_id = context.chat_data.get(PANEL_KEY)
    if old_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=old_id)
        except Exception:
            pass

    new_message = await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    await save_panel(context, new_message)


def main_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("🎓 School", callback_data="school"),
            InlineKeyboardButton("🌐 Browser", callback_data="browser"),
        ],
        [
            InlineKeyboardButton("⌨️ Keyboard", callback_data="keyboard"),
            InlineKeyboardButton("🧩 Commands", callback_data="commands"),
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
            InlineKeyboardButton("📊 Status", callback_data="status"),
        ],
        [
            InlineKeyboardButton("🔒 Lock", callback_data="lock"),
            InlineKeyboardButton("🔓 Unlock", callback_data="unlock"),
        ],
        [InlineKeyboardButton("⏻ Shutdown", callback_data="shutdown")],
    ]
    return InlineKeyboardMarkup(rows)


def school_keyboard() -> InlineKeyboardMarkup:
    settings = load_settings()
    state = "🟢 ON" if settings["school_enabled"] else "🔴 OFF"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"School Mode {state}", callback_data="toggle_school")],
        [
            InlineKeyboardButton("🎥 Zoom", callback_data="open_zoom"),
            InlineKeyboardButton("🏫 LAUSD", callback_data="open_schoology"),
        ],
        [InlineKeyboardButton("▶️ Run full School Mode", callback_data="run_school")],
        [InlineKeyboardButton("⚙️ Schedule", callback_data="settings")],
        [InlineKeyboardButton("⬅️ Home", callback_data="home")],
    ])


def browser_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️ Back", callback_data="browser:back"),
            InlineKeyboardButton("➡️ Forward", callback_data="browser:forward"),
        ],
        [InlineKeyboardButton("🔄 Reload", callback_data="browser:reload")],
        [InlineKeyboardButton("🔗 Open URL", callback_data="browser:url")],
        [InlineKeyboardButton("⬅️ Home", callback_data="home")],
    ])


def keyboard_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("ESC", callback_data="key:ESC"), InlineKeyboardButton("TAB", callback_data="key:TAB"), InlineKeyboardButton("ENTER", callback_data="key:ENTER")],
        [InlineKeyboardButton("←", callback_data="key:LEFT"), InlineKeyboardButton("↑", callback_data="key:UP"), InlineKeyboardButton("↓", callback_data="key:DOWN"), InlineKeyboardButton("→", callback_data="key:RIGHT")],
        [InlineKeyboardButton("CTRL+C", callback_data="key:CTRL+C"), InlineKeyboardButton("CTRL+V", callback_data="key:CTRL+V"), InlineKeyboardButton("CTRL+L", callback_data="key:CTRL+L")],
        [InlineKeyboardButton("ALT+TAB", callback_data="key:ALT+TAB"), InlineKeyboardButton("ALT+F4", callback_data="key:ALT+F4")],
        [InlineKeyboardButton("⌨️ Type text", callback_data="type_text")],
        [InlineKeyboardButton("⬅️ Home", callback_data="home")],
    ]
    return InlineKeyboardMarkup(rows)


def commands_keyboard() -> InlineKeyboardMarkup:
    commands = load_commands()
    rows = [
        [InlineKeyboardButton("📤 Upload command pack", callback_data="upload_pack")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="commands")],
    ]

    for command in commands[:30]:
        rows.append([
            InlineKeyboardButton(
                command["title"][:40],
                callback_data=f"cmd:{command['id']}",
            )
        ])

    rows.append([InlineKeyboardButton("⬅️ Home", callback_data="home")])
    return InlineKeyboardMarkup(rows)


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
        [InlineKeyboardButton("⬅️ Home", callback_data="home")],
    ])


def panel_text() -> str:
    s = load_settings()
    return (
        "<b>b1o Remote</b>\n\n"
        f"School Mode: <b>{'ON' if s['school_enabled'] else 'OFF'}</b>\n"
        f"School: <b>{html.escape(str(s['school_time']))}</b>\n"
        f"Zoom: <b>{html.escape(str(s['zoom_time']))}</b>\n"
        f"Days: <b>{html.escape(','.join(map(str, s['school_days'])))}</b>"
    )


def school_text() -> str:
    s = load_settings()
    return (
        "<b>🎓 School Mode</b>\n\n"
        f"Status: <b>{'ON' if s['school_enabled'] else 'OFF'}</b>\n"
        f"School time: <b>{html.escape(str(s['school_time']))}</b>\n"
        f"Zoom time: <b>{html.escape(str(s['zoom_time']))}</b>\n"
        f"Days: <b>{html.escape(','.join(map(str, s['school_days'])))}</b>"
    )


def settings_text() -> str:
    s = load_settings()
    return (
        "<b>⚙️ Settings</b>\n\n"
        f"Schoology: <code>{html.escape(s['schoology_user'] or 'not set')}</code>\n"
        f"Schoology password: <b>{'set' if s['schoology_password'] else 'not set'}</b>\n"
        f"School time: <b>{html.escape(str(s['school_time']))}</b>\n"
        f"Zoom time: <b>{html.escape(str(s['zoom_time']))}</b>\n"
        f"Zoom URL: <code>{html.escape(s['zoom_url'] or 'not set')}</code>\n"
        f"Brave: <code>{html.escape(s['browser'])}</code>"
    )


def valid_time(value: str) -> bool:
    return bool(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", value.strip()))


def valid_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def command_actions(command: dict) -> list[dict]:
    return command["actions"]


async def execute_command(command: dict) -> None:
    for action in command_actions(command):
        action_type = action["type"]
        if action_type == "open_url":
            await agent_request("POST", "/open-url", {"url": action["url"]})
        elif action_type == "key":
            await agent_request("POST", "/input/key", {"combo": action["combo"]})
        elif action_type == "type":
            await agent_request("POST", "/input/type", {"text": action["text"]})
        elif action_type == "open_zoom":
            await agent_request("POST", "/open-zoom")
        elif action_type == "open_schoology":
            await agent_request("POST", "/open-schoology")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        return

    pending = context.user_data.pop(PENDING_KEY, None)
    if not pending:
        await delete_message(update.message)
        return

    value = update.message.text or ""
    await delete_message(update.message)

    if pending == "unlock_password":
        try:
            result = await agent_request(
                "POST",
                "/unlock-password",
                {"password": value},
            )
            text = (
                "🔓 Password sent to the local unlock helper."
                if result.get("success")
                else "❌ Unlock helper failed."
            )
        except Exception as exc:
            text = f"❌ Unlock failed: {type(exc).__name__}"
        await replace_panel(update, context, text, main_keyboard())
        return

    key = pending
    if key == "school_days":
        try:
            days = sorted(set(int(v.strip()) for v in value.split(",")))
            if not days or any(v < 0 or v > 6 for v in days):
                raise ValueError
            value = days
        except ValueError:
            await replace_panel(
                update, context,
                "📅 Use days 0-6, for example <code>0,1,2,3,4</code>.",
                settings_keyboard(),
            )
            return

    if key in {"school_time", "zoom_time"} and not valid_time(value):
        await replace_panel(update, context, "⏰ Use HH:MM.", settings_keyboard())
        return

    if key in {"schoology_url", "zoom_url"} and not valid_url(value):
        await replace_panel(update, context, "🔗 Send a valid http/https URL.", settings_keyboard())
        return

    if key == "browser" and not value.startswith("/"):
        await replace_panel(update, context, "🌐 Send an absolute Brave path.", settings_keyboard())
        return

    settings = load_settings()
    settings[key] = value
    save_settings(settings)

    await replace_panel(
        update,
        context,
        "✅ Saved.",
        settings_keyboard(),
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        await delete_message(update.message)
        return

    if context.user_data.get(PENDING_KEY) != "upload_pack":
        await delete_message(update.message)
        return

    context.user_data.pop(PENDING_KEY, None)

    document = update.message.document
    if not document:
        return

    try:
        telegram_file = await document.get_file()
        content = bytes(await telegram_file.download_as_bytearray())
        commands = install_pack(content, document.file_name or "commands.json")
        message = f"✅ Installed {len(commands)} command(s)."
    except Exception as exc:
        message = f"❌ Upload failed: {type(exc).__name__}"

    await delete_message(update.message)
    await replace_panel(update, context, message, commands_keyboard())


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not allowed(update):
        await delete_message(update.message)
        return

    await delete_message(update.message)
    old_id = context.chat_data.get(PANEL_KEY)
    if old_id:
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=old_id,
            )
        except Exception:
            pass

    message = await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=panel_text(),
        reply_markup=main_keyboard(),
        parse_mode=ParseMode.HTML,
    )
    await save_panel(context, message)


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if not allowed(update):
        return

    data = query.data or ""

    try:
        if data == "home":
            await replace_panel(update, context, panel_text(), main_keyboard())
            return

        if data == "school":
            await replace_panel(update, context, school_text(), school_keyboard())
            return

        if data == "toggle_school":
            settings = load_settings()
            settings["school_enabled"] = not settings["school_enabled"]
            save_settings(settings)
            await replace_panel(update, context, school_text(), school_keyboard())
            return

        if data == "open_zoom":
            await agent_request("POST", "/open-zoom")
            await replace_panel(update, context, "🎥 Zoom opened.", school_keyboard())
            return

        if data == "open_schoology":
            await agent_request("POST", "/open-schoology")
            await replace_panel(update, context, "🏫 LAUSD opened.", school_keyboard())
            return

        if data == "run_school":
            await replace_panel(update, context, "🚀 Starting School Mode...", school_keyboard())
            context.application.create_task(asyncio.to_thread(open_school_session))
            return

        if data == "browser":
            await replace_panel(update, context, "🌐 Browser", browser_keyboard())
            return

        if data.startswith("browser:"):
            action = data.split(":", 1)[1]
            combos = {
                "back": ["ALT", "LEFT"],
                "forward": ["ALT", "RIGHT"],
                "reload": ["CTRL", "R"],
            }
            if action in combos:
                await agent_request("POST", "/input/key", {"combo": combos[action]})
                await replace_panel(update, context, "✅ Browser action sent.", browser_keyboard())
                return

            if action == "url":
                context.user_data[PENDING_KEY] = "browser_url"
                await replace_panel(update, context, "🔗 Send a URL.", browser_keyboard())
                return

        if data == "keyboard":
            await replace_panel(update, context, "⌨️ Remote keyboard", keyboard_keyboard())
            return

        if data == "type_text":
            context.user_data[PENDING_KEY] = "type_text"
            await replace_panel(update, context, "⌨️ Send the text to type.", keyboard_keyboard())
            return

        if data.startswith("key:"):
            combo = data.split(":", 1)[1].split("+")
            await agent_request("POST", "/input/key", {"combo": combo})
            await replace_panel(update, context, "✅ Key sent.", keyboard_keyboard())
            return

        if data == "commands":
            await replace_panel(update, context, "🧩 <b>Commands</b>", commands_keyboard())
            return

        if data == "upload_pack":
            context.user_data[PENDING_KEY] = "upload_pack"
            await replace_panel(
                update,
                context,
                "📤 Send a <code>.json</code> command pack.\nOnly safe actions are allowed: URL, key combo, text, Zoom, LAUSD.",
                commands_keyboard(),
            )
            return

        if data.startswith("cmd:"):
            command_id = data.split(":", 1)[1]
            command = next(
                (item for item in load_commands() if item["id"] == command_id),
                None,
            )
            if command is None:
                await replace_panel(update, context, "❌ Command not found.", commands_keyboard())
                return

            await execute_command(command)
            await replace_panel(
                update,
                context,
                f"✅ {html.escape(command['title'])}",
                commands_keyboard(),
            )
            return

        if data == "settings":
            await replace_panel(update, context, settings_text(), settings_keyboard())
            return

        if data.startswith("set:"):
            key = data.split(":", 1)[1]
            context.user_data[PENDING_KEY] = key
            prompts = {
                "schoology_url": "🌐 Send Schoology Student Login URL.",
                "schoology_user": "📧 Send Schoology email.",
                "schoology_password": "🔑 Send Schoology password. The message will be deleted immediately; the password is stored locally.",
                "school_time": "⏰ Send School time as HH:MM.",
                "zoom_time": "🎥 Send Zoom time as HH:MM.",
                "school_days": "📅 Send days 0-6, e.g. 0,1,2,3,4.",
                "zoom_url": "🔗 Send the Zoom lesson URL.",
                "browser": "🌐 Send Brave path, e.g. /usr/bin/brave.",
                "browser_profile": "📁 Send browser profile path.",
            }
            await replace_panel(update, context, prompts[key], settings_keyboard())
            return

        if data == "unlock":
            context.user_data[PENDING_KEY] = "unlock_password"
            await replace_panel(
                update,
                context,
                "🔓 Send your PC password once. It will not be stored by the bot and the Telegram message will be deleted after receipt.",
                main_keyboard(),
            )
            return

        if data == "status":
            result = await agent_request("GET", "/status")
            await replace_panel(
                update,
                context,
                f"🟢 Online\nHost: <code>{html.escape(result['hostname'])}</code>",
                main_keyboard(),
            )
            return

        if data == "lock":
            await agent_request("POST", "/lock")
            await replace_panel(update, context, "🔒 Locked.", main_keyboard())
            return

        if data == "shutdown":
            await agent_request("POST", "/shutdown")
            await replace_panel(update, context, "⏻ Shutdown requested.", main_keyboard())
            return

    except Exception as exc:
        await replace_panel(
            update,
            context,
            f"❌ Error: {type(exc).__name__}",
            main_keyboard(),
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
        MessageHandler(filters.Document.ALL, handle_document)
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )
    app.run_polling()


if __name__ == "__main__":
    main()
