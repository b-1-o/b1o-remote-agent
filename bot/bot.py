import asyncio
import html
import os

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from commands_store import load_commands
from config_store import load_settings
from runner import execute_command_sync
from automation.school import open_school_session, open_schoology_session

AGENT_URL = os.getenv("B1O_AGENT_URL", "http://127.0.0.1:8765")
AGENT_TOKEN = os.getenv("B1O_REMOTE_TOKEN", "")
TELEGRAM_TOKEN = os.getenv("B1O_TELEGRAM_TOKEN", "")
ALLOWED_CHAT_ID = os.getenv("B1O_TELEGRAM_CHAT_ID", "")
PANEL_KEY = "panel_id"

def allowed(update: Update) -> bool:
    return bool(ALLOWED_CHAT_ID) and update.effective_chat is not None and str(update.effective_chat.id) == ALLOWED_CHAT_ID

async def agent(method: str, path: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.request(method, AGENT_URL + path, headers={"X-Agent-Token": AGENT_TOKEN})
        r.raise_for_status()
        return r.json()

async def delete_message(message) -> None:
    try: await message.delete()
    except Exception: pass

def home_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("🎓 School Mode", callback_data="school")],
            [InlineKeyboardButton("🧩 Actions", callback_data="actions")],
            [InlineKeyboardButton("📊 Status", callback_data="status")],
            [InlineKeyboardButton("🔓 Unlock", callback_data="unlock"), InlineKeyboardButton("🔒 Lock", callback_data="lock")],
            [InlineKeyboardButton("⏻ Shutdown", callback_data="shutdown")]]
    return InlineKeyboardMarkup(rows)

def school_keyboard() -> InlineKeyboardMarkup:
    s=load_settings(); state="🟢 ON" if s['school_enabled'] else "🔴 OFF"
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"School Mode {state}", callback_data="toggle_school")],
        [InlineKeyboardButton("🎥 Zoom", callback_data="zoom"), InlineKeyboardButton("🏫 LAUSD", callback_data="lausd")],
        [InlineKeyboardButton("▶️ Run scheduled School Mode", callback_data="run_school")],
        [InlineKeyboardButton("⬅️ Home", callback_data="home")]])

def actions_keyboard() -> InlineKeyboardMarkup:
    rows=[]
    # Zoom and LAUSD are fixed School Mode controls, not custom Actions.
    custom_commands = [
        cmd for cmd in load_commands()
        if cmd["id"] not in {"open_zoom", "open_schoology"}
    ]
    for cmd in custom_commands[:30]:
        rows.append([InlineKeyboardButton(cmd['title'][:48], callback_data=f"cmd:{cmd['id']}")])
    if not rows: rows=[[InlineKeyboardButton("No custom buttons yet", callback_data="noop")]]
    rows.append([InlineKeyboardButton("⬅️ Home", callback_data="home")])
    return InlineKeyboardMarkup(rows)

def home_text() -> str:
    s=load_settings()
    return f"<b>b1o Remote</b>\n\nSchool Mode: <b>{'ON' if s['school_enabled'] else 'OFF'}</b>\nSchedule: <b>{html.escape(s['school_time'])}</b>\nZoom: <b>{html.escape(s['zoom_time'])}</b>"

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, keyboard: InlineKeyboardMarkup):
    q=update.callback_query
    if q:
        try:
            await q.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
            context.chat_data[PANEL_KEY]=q.message.message_id
            return
        except Exception: pass
    chat_id=update.effective_chat.id
    old=context.chat_data.get(PANEL_KEY)
    if old:
        try: await context.bot.delete_message(chat_id, old)
        except Exception: pass
    m=await context.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
    context.chat_data[PANEL_KEY]=m.message_id

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): await delete_message(update.message); return
    await delete_message(update.message)
    await panel(update, context, home_text(), home_keyboard())

async def text_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_message(update.message)


async def background_schoology(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await asyncio.to_thread(open_schoology_session)
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        await panel(
            update,
            context,
            f"❌ LAUSD: {html.escape(message)[:240]}",
            school_keyboard(),
        )


async def background_school(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await asyncio.to_thread(open_school_session)
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        await panel(
            update,
            context,
            f"❌ School Mode: {html.escape(message)[:240]}",
            school_keyboard(),
        )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    if not allowed(update): return
    data=q.data or ""
    try:
        if data=="home": await panel(update,context,home_text(),home_keyboard()); return
        if data=="school": await panel(update,context,"<b>🎓 School Mode</b>\n\nOnly use controls below. Configuration is managed on the PC admin site.",school_keyboard()); return
        if data=="toggle_school":
            from config_store import save_settings
            s=load_settings(); s['school_enabled']=not s['school_enabled']; save_settings(s)
            await panel(update,context,"<b>🎓 School Mode</b>",school_keyboard()); return
        if data=="zoom": await agent('POST','/open-zoom'); await panel(update,context,'🎥 Zoom opened.',school_keyboard()); return
        if data=="lausd":
            asyncio.create_task(background_schoology(update, context))
            await panel(update,context,'🏫 LAUSD login started.',school_keyboard())
            return
        if data=="run_school":
            asyncio.create_task(background_school(update, context))
            await panel(update,context,'🚀 School Mode started.',school_keyboard()); return
        if data=="actions": await panel(update,context,'<b>🧩 Actions</b>\nButtons installed from the PC admin panel.',actions_keyboard()); return
        if data.startswith('cmd:'):
            command_id = data.split(':',1)[1]
            command = next(
                (item for item in load_commands() if item['id'] == command_id),
                None,
            )
            if command is None:
                raise RuntimeError('Command not found')

            try:
                await asyncio.to_thread(execute_command_sync, command)
            except Exception as exc:
                raise RuntimeError(
                    f"Command {command_id} failed: {type(exc).__name__}: {exc}"
                ) from exc

            await panel(
                update,
                context,
                f"✅ {html.escape(command['title'])}",
                actions_keyboard(),
            )
            return
        if data=='status':
            r=await agent('GET','/status'); await panel(update,context,f"🟢 Online\nHost: <code>{html.escape(r['hostname'])}</code>",home_keyboard()); return
        if data=='unlock':
            await agent('POST','/unlock'); await panel(update,context,'🔓 Unlock command sent.',home_keyboard()); return
        if data=='lock': await agent('POST','/lock'); await panel(update,context,'🔒 Locked.',home_keyboard()); return
        if data=='shutdown': await agent('POST','/shutdown'); await panel(update,context,'⏻ Shutdown requested.',home_keyboard()); return
        if data=='noop': return
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        await panel(
            update,
            context,
            f"❌ {html.escape(message)[:220]}",
            home_keyboard(),
        )

def main() -> None:
    if not TELEGRAM_TOKEN: raise RuntimeError('B1O_TELEGRAM_TOKEN is not configured')
    if not AGENT_TOKEN: raise RuntimeError('B1O_REMOTE_TOKEN is not configured')
    if not ALLOWED_CHAT_ID: raise RuntimeError('B1O_TELEGRAM_CHAT_ID is not configured')
    app=Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler('start',start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, text_fallback))
    app.run_polling()

if __name__=='__main__': main()