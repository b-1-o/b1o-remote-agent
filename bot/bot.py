import asyncio
import html
import os
from pathlib import Path

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from commands_store import load_commands
from config_store import load_settings

AGENT_URL = os.getenv("B1O_AGENT_URL", "http://127.0.0.1:8765")
AGENT_TOKEN = os.getenv("B1O_REMOTE_TOKEN", "")
TELEGRAM_TOKEN = os.getenv("B1O_TELEGRAM_TOKEN", "")
ALLOWED_CHAT_ID = os.getenv("B1O_TELEGRAM_CHAT_ID", "")
PANEL_KEY = "panel_id"
PANEL_HISTORY_KEY = "panel_history"
MAX_PANEL_HISTORY = 8
ZOOM_READY_IMAGE = Path.home() / ".cache" / "b1o-remote" / "zoom_ready.png"

def allowed(update: Update) -> bool:
    return bool(ALLOWED_CHAT_ID) and update.effective_chat is not None and str(update.effective_chat.id) == ALLOWED_CHAT_ID

async def agent(method: str, path: str) -> dict:
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.request(
            method,
            AGENT_URL + path,
            headers={"X-Agent-Token": AGENT_TOKEN},
        )
        if not r.is_success:
            raise RuntimeError(
                f"Agent HTTP {r.status_code}: {r.text[:240]}"
            )
        return r.json()

async def delete_message(message) -> None:
    try: await message.delete()
    except Exception: pass

def home_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("🎓 School Mode", callback_data="school")],
            [InlineKeyboardButton("💬 Zoom Chat", callback_data="zoom_chat")],
            [InlineKeyboardButton("🌫 Browser", callback_data="browser")],
            [InlineKeyboardButton("🧩 Actions", callback_data="actions")],
            [InlineKeyboardButton("📊 Status", callback_data="status")],
            [InlineKeyboardButton("🔓 Unlock", callback_data="unlock"), InlineKeyboardButton("🔒 Lock", callback_data="lock")],
            [InlineKeyboardButton("⏻ Shutdown", callback_data="shutdown")]]
    return InlineKeyboardMarkup(rows)

def school_keyboard() -> InlineKeyboardMarkup:
    s=load_settings(); state="🟢 ON" if s['school_enabled'] else "🔴 OFF"
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"School Mode {state}", callback_data="toggle_school")],
        [InlineKeyboardButton("🎥 Zoom", callback_data="zoom"), InlineKeyboardButton("🏫 LAUSD", callback_data="lausd")],
        [InlineKeyboardButton("✖ Close Conference", callback_data="zoom_close")],
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

def _browser_slot_key(context: ContextTypes.DEFAULT_TYPE, index: int) -> str:
    slots = list(context.chat_data.get("browser_slots", []))
    if 0 <= index < len(slots):
        return str(slots[index])
    raise RuntimeError("Browser tab is no longer available")


def browser_keyboard(tabs: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for index, tab in enumerate(tabs[:12]):
        slot = str(tab.get("slot", "tab"))
        title = str(tab.get("title", "")).strip() or "Untitled"
        url = str(tab.get("url", "")).strip()

        if slot == "zoom":
            icon = "🎥"
            label = "Zoom"
        elif slot == "lausd":
            icon = "🏫"
            label = "LAUSD"
        else:
            icon = "🌐"
            label = title[:24]

        rows.append([
            InlineKeyboardButton(
                f"{icon} {label}",
                callback_data=f"bf:{index}",
            ),
            InlineKeyboardButton("✕", callback_data=f"bc:{index}"),
        ])

    if any(str(tab.get("slot", "")) == "zoom" for tab in tabs):
        rows.append([
            InlineKeyboardButton("💬 Zoom Chat", callback_data="zoom_chat"),
            InlineKeyboardButton("↻ Refresh", callback_data="browser"),
        ])
    else:
        rows.append([InlineKeyboardButton("↻ Refresh", callback_data="browser")])

    rows.append([
        InlineKeyboardButton("⌂ Home", callback_data="home"),
    ])
    return InlineKeyboardMarkup(rows)


def browser_text(tabs: list[dict], updated: bool = False) -> str:
    count = len(tabs)
    pulse = "·  ◌  ·" if updated else "·  ✦  ·"

    lines = [
        "<b>🌫 b1o / BROWSER</b>",
        f"<code>{pulse}</code>  <i>live session</i>",
        "",
        f"<b>{count}</b> open " + ("tab" if count == 1 else "tabs"),
        "",
    ]

    if not tabs:
        lines.extend([
            "<i>╭ fog is clear",
            "╰ no managed tabs are open</i>",
        ])
    else:
        for tab in tabs[:12]:
            slot = html.escape(str(tab.get("slot", "tab")))
            title = html.escape(str(tab.get("title", "")).strip() or "Untitled")
            url = html.escape(str(tab.get("url", "")).strip() or "about:blank")
            if len(url) > 68:
                url = url[:65] + "…"
            lines.extend([
                f"🌫 <b>{slot}</b>",
                f"   <i>{title}</i>",
                f"   <code>{url}</code>",
                "",
            ])

    lines.extend([
        "<code>╭────────────────────╮",
        "│   LIVE / MANAGED   │",
        "╰────────────────────╯</code>",
    ])
    return "\n".join(lines)


async def show_browser(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    animated: bool = False,
) -> None:
    q = update.callback_query
    if animated:
        await panel(
            update,
            context,
            "<b>🌫 b1o / BROWSER</b>\n\n<code>·  ◌  ·  ◌  ·</code>\n<i>gliding through open tabs…</i>",
            browser_keyboard([]),
        )

    result = await agent("GET", "/browser/tabs")
    tabs = result.get("tabs") or []
    context.chat_data["browser_slots"] = [
        str(tab.get("slot", "")) for tab in tabs[:12]
    ]
    keyboard = browser_keyboard(tabs)
    text_value = browser_text(tabs, updated=animated)

    if q:
        try:
            await q.message.edit_text(
                text_value,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            context.chat_data[PANEL_KEY] = q.message.message_id
            return
        except Exception:
            pass

    await panel(update, context, text_value, keyboard)


def zoom_chat_keyboard(live: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("↻ Refresh", callback_data="zoom_chat"),
            InlineKeyboardButton(
                "🟢 Live" if live else "⚪ Live",
                callback_data="zoom_chat_live",
            ),
        ],
        [
            InlineKeyboardButton("✖ Close Conference", callback_data="zoom_close"),
        ],
        [
            InlineKeyboardButton("🌫 Browser", callback_data="browser"),
            InlineKeyboardButton("⌂ Home", callback_data="home"),
        ],
    ])


def zoom_chat_text(result: dict) -> str:
    messages = result.get("messages") or []
    is_open = bool(result.get("open"))
    new_messages = result.get("new_messages") or []

    lines = [
        "<b>💬 b1o / ZOOM CHAT</b>",
        "<code>╭────────────────────────╮</code>",
        "<code>│  live meeting channel  │</code>",
        "<code>╰────────────────────────╯</code>",
        "",
    ]

    if not is_open:
        lines.extend([
            "🌫 <i>Zoom tab is not open.</i>",
            "",
            "Open Zoom first, then return here.",
        ])
    elif not messages:
        lines.extend([
            "🌫 <i>Chat is quiet.</i>",
            "",
            "<code>waiting for messages…</code>",
        ])
    else:
        recent = messages[-14:]
        for message in recent:
            text = html.escape(str(message.get("text", "")).strip())
            stamp = html.escape(str(message.get("time", "")).strip())
            if not text:
                continue
            if len(text) > 420:
                text = text[:417] + "…"
            lines.extend([
                f"<code>{stamp}</code>  <b>●</b>",
                f"<i>{text}</i>",
                "<code>────────────</code>",
            ])

        if new_messages:
            lines.insert(4, f"✨ <b>{len(new_messages)} new</b> message" + ("s" if len(new_messages) != 1 else ""))
            lines.insert(5, "")

    lines.extend([
        "",
        f"<i>{len(messages)} messages cached • read-only</i>",
    ])
    return "\n".join(lines)


async def show_zoom_chat(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    live: bool | None = None,
) -> None:
    q = update.callback_query

    if live is not None:
        context.chat_data["zoom_chat_live"] = bool(live)

    current_live = bool(context.chat_data.get("zoom_chat_live", False))
    try:
        result = await agent("GET", "/browser/chat")
    except Exception as exc:
        result = {
            "open": False,
            "messages": [],
            "error": str(exc),
        }

    if result.get("error"):
        text_value = (
            "<b>💬 b1o / ZOOM CHAT</b>\n\n"
            f"❌ <code>{html.escape(str(result['error']))[:900]}</code>"
        )
    else:
        text_value = zoom_chat_text(result)

    keyboard = zoom_chat_keyboard(current_live)

    if q:
        try:
            await q.message.edit_text(
                text_value,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            context.chat_data[PANEL_KEY] = q.message.message_id
            context.chat_data["zoom_chat_message_id"] = q.message.message_id
            context.chat_data["_chat_id"] = update.effective_chat.id
            return
        except Exception:
            pass

    await panel(update, context, text_value, keyboard)


async def zoom_chat_live_loop(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = context.chat_data.get("_chat_id")
    message_id = context.chat_data.get("zoom_chat_message_id")
    if not chat_id or not message_id:
        return

    while context.chat_data.get("zoom_chat_live", False):
        try:
            result = await agent("GET", "/browser/chat")
            text_value = zoom_chat_text(result)
            keyboard = zoom_chat_keyboard(True)
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text_value,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        except Exception:
            pass
        await asyncio.sleep(3)


async def ensure_zoom_chat_live(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    context.chat_data["_chat_id"] = update.effective_chat.id
    q = update.callback_query
    if q and q.message:
        context.chat_data["zoom_chat_message_id"] = q.message.message_id

    task = context.chat_data.get("zoom_chat_task")
    if task is not None and not task.done():
        return

    task = asyncio.create_task(zoom_chat_live_loop(context))
    context.chat_data["zoom_chat_task"] = task


async def stop_zoom_chat_live(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.chat_data["zoom_chat_live"] = False
    task = context.chat_data.pop("zoom_chat_task", None)
    if task is not None and not task.done():
        task.cancel()


def shutdown_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚠️ Tap again to Shutdown", callback_data="shutdown_confirm")],
        [InlineKeyboardButton("↩ Cancel", callback_data="home")],
    ])


def home_text() -> str:
    s=load_settings()
    return f"<b>b1o Remote</b>\n\nSchool Mode: <b>{'ON' if s['school_enabled'] else 'OFF'}</b>\nSchedule: <b>{html.escape(s['school_time'])}</b>\nZoom: <b>{html.escape(s['zoom_time'])}</b>"

async def _delete_old_panels(context: ContextTypes.DEFAULT_TYPE, chat_id: int, keep_id: int | None = None) -> None:
    history = list(context.chat_data.get(PANEL_HISTORY_KEY, []))
    keep: list[int] = []
    for message_id in history:
        if keep_id is not None and message_id == keep_id:
            keep.append(message_id)
            continue
        try:
            await context.bot.delete_message(chat_id, message_id)
        except Exception:
            pass
    context.chat_data[PANEL_HISTORY_KEY] = keep

async def panel(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, keyboard: InlineKeyboardMarkup):
    q=update.callback_query
    chat_id=update.effective_chat.id

    if q:
        try:
            message_id = q.message.message_id
            await q.message.edit_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            context.chat_data[PANEL_KEY] = message_id
            history = list(context.chat_data.get(PANEL_HISTORY_KEY, []))
            if message_id not in history:
                history.append(message_id)
            context.chat_data[PANEL_HISTORY_KEY] = history[-MAX_PANEL_HISTORY:]
            await _delete_old_panels(context, chat_id, keep_id=message_id)
            return
        except Exception:
            pass

    old = context.chat_data.get(PANEL_KEY)
    await _delete_old_panels(context, chat_id, keep_id=None)

    m=await context.bot.send_message(
        chat_id,
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    context.chat_data[PANEL_KEY]=m.message_id
    context.chat_data[PANEL_HISTORY_KEY]=[m.message_id]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update): await delete_message(update.message); return
    await stop_zoom_chat_live(context)
    await delete_message(update.message)
    await panel(update, context, home_text(), home_keyboard())

async def text_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_message(update.message)

async def command_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await delete_message(update.message)


async def background_schoology(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await agent('POST','/open-schoology-login')
    except Exception as exc:
        message = str(exc) or type(exc).__name__
        await panel(
            update,
            context,
            f"❌ LAUSD: {html.escape(message)[:240]}",
            school_keyboard(),
        )


def create_zoom_ready_image() -> Path:
    from PIL import Image, ImageDraw, ImageFont

    ZOOM_READY_IMAGE.parent.mkdir(parents=True, exist_ok=True)

    width, height = 900, 520
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    blue = (45, 117, 240)
    dark = (28, 28, 32)

    # Minimal Zoom-style camera logo.
    logo_size = 150
    logo_x = (width - logo_size) // 2
    logo_y = 70
    radius = 34
    draw.rounded_rectangle(
        (logo_x, logo_y, logo_x + logo_size, logo_y + logo_size),
        radius=radius,
        fill=blue,
    )
    draw.rounded_rectangle(
        (logo_x + 36, logo_y + 48, logo_x + 90, logo_y + 102),
        radius=12,
        fill="white",
    )
    draw.polygon(
        [
            (logo_x + 90, logo_y + 58),
            (logo_x + 116, logo_y + 45),
            (logo_x + 116, logo_y + 105),
            (logo_x + 90, logo_y + 92),
        ],
        fill="white",
    )

    font_candidates = [
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    regular_candidates = [
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]

    bold_font = None
    regular_font = None
    for path in font_candidates:
        if Path(path).is_file():
            bold_font = ImageFont.truetype(path, 50)
            break
    for path in regular_candidates:
        if Path(path).is_file():
            regular_font = ImageFont.truetype(path, 28)
            break

    if bold_font is None:
        bold_font = ImageFont.load_default()
    if regular_font is None:
        regular_font = ImageFont.load_default()

    title = "Zoom ready to join"
    bbox = draw.textbbox((0, 0), title, font=bold_font)
    title_w = bbox[2] - bbox[0]
    title_x = (width - title_w) // 2
    draw.text((title_x, 270), title, fill=dark, font=bold_font)

    subtitle = "Microphone OFF  •  Camera OFF"
    bbox = draw.textbbox((0, 0), subtitle, font=regular_font)
    subtitle_w = bbox[2] - bbox[0]
    draw.text(
        ((width - subtitle_w) // 2, 350),
        subtitle,
        fill=(90, 90, 96),
        font=regular_font,
    )

    image.save(ZOOM_READY_IMAGE, format="PNG", optimize=True)
    return ZOOM_READY_IMAGE


async def zoom_ready_panel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    chat_id = update.effective_chat.id
    await _delete_old_panels(context, chat_id)

    try:
        image_path = create_zoom_ready_image()
        with image_path.open("rb") as image_file:
            message = await context.bot.send_photo(
                chat_id=chat_id,
                photo=image_file,
                caption=(
                    "<b>Zoom ready to join</b>\n"
                    "Name: <b>Erik</b>\n"
                    "🎙️ Microphone: <b>OFF</b>\n"
                    "📷 Camera: <b>OFF</b>"
                ),
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Join", callback_data="zoom_join")],
                    [InlineKeyboardButton("Cancel", callback_data="zoom_cancel")],
                ]),
            )

        context.chat_data[PANEL_KEY] = message.message_id
        context.chat_data[PANEL_HISTORY_KEY] = [message.message_id]
        return
    except Exception:
        # Keep the Join control available even if Telegram rejects the image.
        message = await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "<b>Zoom ready to join</b>\n"
                "Name: <b>Erik</b>\n"
                "🎙️ Microphone: <b>OFF</b>\n"
                "📷 Camera: <b>OFF</b>"
            ),
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Join", callback_data="zoom_join")],
                [InlineKeyboardButton("Cancel", callback_data="zoom_cancel")],
            ]),
        )
        context.chat_data[PANEL_KEY] = message.message_id
        context.chat_data[PANEL_HISTORY_KEY] = [message.message_id]


async def background_school(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await agent('POST','/school/start')
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
        if data=="home":
            await stop_zoom_chat_live(context)
            await panel(update,context,home_text(),home_keyboard())
            return
        if data=="zoom_chat":
            await show_zoom_chat(update, context)
            return
        if data=="zoom_chat_live":
            enabled = not bool(context.chat_data.get("zoom_chat_live", False))
            if enabled:
                await show_zoom_chat(update, context, live=True)
                await ensure_zoom_chat_live(update, context)
            else:
                await stop_zoom_chat_live(context)
                await show_zoom_chat(update, context, live=False)
            return
        if data=="school":
            await stop_zoom_chat_live(context)
            await panel(update,context,"<b>🎓 School Mode</b>\n\nOnly use controls below. Configuration is managed on the PC admin site.",school_keyboard())
            return
        if data=="browser":
            await stop_zoom_chat_live(context)
            await show_browser(update, context, animated=True)
            return
        if data.startswith("bf:"):
            index = int(data.split(":", 1)[1])
            slot = _browser_slot_key(context, index)
            await agent("POST", f"/browser/focus/{slot}")
            await show_browser(update, context)
            return
        if data.startswith("bc:"):
            index = int(data.split(":", 1)[1])
            slot = _browser_slot_key(context, index)
            if slot == "zoom":
                await agent("POST", "/zoom/cancel")
            else:
                await agent("POST", f"/browser/close/{slot}")
            await show_browser(update, context)
            return

        if data=="toggle_school":
            from config_store import save_settings
            s=load_settings(); s['school_enabled']=not s['school_enabled']; save_settings(s)
            await panel(update,context,"<b>🎓 School Mode</b>",school_keyboard()); return
        if data=="zoom":
            await agent('POST', '/zoom/start')
            await panel(
                update,
                context,
                "🎥 <b>Preparing Zoom…</b>",
                school_keyboard(),
            )

            for _ in range(90):
                await asyncio.sleep(1)
                state = await agent('GET', '/zoom/state')
                status = state.get("status")

                if status == "ready" and state.get("ready"):
                    await zoom_ready_panel(update, context)
                    return

                if status == "error":
                    raise RuntimeError(
                        f"Zoom: {state.get('error') or 'pre-join failed'}"
                    )

            raise RuntimeError("Zoom preparation timed out")

        if data=="zoom_join":
            try:
                await q.message.edit_caption(
                    caption="<b>Joining Zoom…</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=None,
                )
            except Exception:
                pass

            await agent('POST', '/join-zoom')

            try:
                await q.message.delete()
            except Exception:
                pass

            await panel(
                update,
                context,
                "✅ <b>Joined Zoom</b>",
                school_keyboard(),
            )
            return
        if data=="zoom_cancel":
            await agent('POST', '/zoom/cancel')
            try:
                await q.message.delete()
            except Exception:
                pass
            await panel(
                update,
                context,
                "✖️ <b>Zoom cancelled</b>",
                school_keyboard(),
            )
            return
        if data=="zoom_close":
            await stop_zoom_chat_live(context)
            await agent('POST', '/zoom/close')
            try:
                await q.message.delete()
            except Exception:
                pass
            await panel(
                update,
                context,
                "✖️ <b>Conference closed</b>",
                school_keyboard(),
            )
            return
        if data=="lausd":
            await panel(
                update,
                context,
                "🌫 <b>Opening LAUSD…</b>\n\n<code>·  ◌  ·  ◌  ·</code>",
                school_keyboard(),
            )
            try:
                result = await agent('POST', '/open-schoology-login')
            except Exception as exc:
                await panel(
                    update,
                    context,
                    f"❌ <b>LAUSD</b>\n\n<code>{html.escape(str(exc))[:900]}</code>",
                    school_keyboard(),
                )
                return

            url = html.escape(str(result.get('url', '')))
            login_done = result.get('login_completed')
            if login_done is False:
                await panel(
                    update,
                    context,
                    f"⚠️ <b>LAUSD opened</b>\n\nLogin was not completed automatically.\n\n<code>{url}</code>",
                    school_keyboard(),
                )
            else:
                await panel(
                    update,
                    context,
                    f"✓ <b>LAUSD ready</b>\n\n<code>{url}</code>",
                    school_keyboard(),
                )
            return
        if data=="run_school":
            asyncio.create_task(background_school(update, context))
            await panel(update,context,'🚀 School Mode started.',school_keyboard()); return
        if data=="actions":
            await stop_zoom_chat_live(context)
            await panel(update,context,'<b>🧩 Actions</b>\nButtons installed from the PC admin panel.',actions_keyboard())
            return
        if data.startswith('cmd:'):
            command_id = data.split(':',1)[1]
            command = next(
                (item for item in load_commands() if item['id'] == command_id),
                None,
            )
            if command is None:
                raise RuntimeError('Command not found')

            try:
                await agent('POST','/run-command', command)
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
        if data=='shutdown':
            await panel(
                update,
                context,
                "<b>⚠️ Shutdown</b>\n\nTap the button again to turn off the PC.",
                shutdown_confirm_keyboard(),
            )
            return

        if data=='shutdown_confirm':
            await agent('POST','/shutdown')
            await panel(
                update,
                context,
                "⏻ <b>Shutdown requested.</b>",
                home_keyboard(),
            )
            return
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
    app.add_handler(MessageHandler(filters.COMMAND, command_fallback))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, text_fallback))
    app.run_polling()

if __name__=='__main__': main()