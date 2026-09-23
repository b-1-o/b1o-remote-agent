import os
import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

AGENT_URL = os.getenv("B1O_AGENT_URL", "http://127.0.0.1:8765")
AGENT_TOKEN = os.getenv("B1O_REMOTE_TOKEN", "")
TELEGRAM_TOKEN = os.getenv("B1O_TELEGRAM_TOKEN", "")
ALLOWED_CHAT_ID = os.getenv("B1O_TELEGRAM_CHAT_ID", "")

def allowed(update: Update) -> bool:
    return bool(ALLOWED_CHAT_ID) and str(update.effective_chat.id) == ALLOWED_CHAT_ID

async def agent_request(method: str, path: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.request(
            method,
            f"{AGENT_URL}{path}",
            headers={"X-Agent-Token": AGENT_TOKEN},
        )
        response.raise_for_status()
        return response.json()

def keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎓 START CLASS", callback_data="zoom")],
        [InlineKeyboardButton("📊 STATUS", callback_data="status")],
        [InlineKeyboardButton("🔒 LOCK", callback_data="lock")],
        [InlineKeyboardButton("⏻ SHUTDOWN", callback_data="shutdown")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not allowed(update):
        return
    await update.message.reply_text("b1o Remote", reply_markup=keyboard())

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not allowed(update):
        return
    try:
        if query.data == "zoom":
            result = await agent_request("POST", "/open-zoom")
            text = "🎓 Zoom opened." if result.get("success") else "Zoom failed."
        elif query.data == "status":
            result = await agent_request("GET", "/status")
            text = f"🟢 Online\nHost: {result['hostname']}"
        elif query.data == "lock":
            result = await agent_request("POST", "/lock")
            text = "🔒 PC locked."
        elif query.data == "shutdown":
            result = await agent_request("POST", "/shutdown")
            text = "⏻ Shutdown requested."
        else:
            text = "Unknown action."
    except Exception as exc:
        text = f"❌ Agent error: {type(exc).__name__}"
    await query.edit_message_text(text, reply_markup=keyboard())

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
    app.run_polling()

if __name__ == "__main__":
    main()
