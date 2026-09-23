from typing import Any

from fastapi import FastAPI, Header, HTTPException

from .actions import (
    browser_close,
    browser_focus,
    browser_tabs,
    browser_zoom_chat,
    get_status,
    login_schoology,
    open_url,
    open_zoom,
    run_command,
    start_school_mode,
)
from .actions import lock_pc, open_schoology, shutdown_pc
from .config import AGENT_TOKEN
from .input_actions import type_text, unlock_configured, send_key

app = FastAPI(title="b1o Remote Agent", version="0.3.0")


def authenticate(token: str | None) -> None:
    if token != AGENT_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")


@app.get("/")
def root():
    return {"name": "b1o Remote Agent", "status": "running"}


@app.get("/status")
def status(x_agent_token: str | None = Header(default=None)):
    authenticate(x_agent_token)
    return get_status()


@app.get("/browser/tabs")
def browser_tab_status(x_agent_token: str | None = Header(default=None)):
    authenticate(x_agent_token)
    return {"tabs": browser_tabs()}


@app.get("/browser/chat")
def browser_chat(x_agent_token: str | None = Header(default=None)):
    authenticate(x_agent_token)
    return browser_zoom_chat()


@app.post("/browser/focus/{slot}")
def focus_browser(slot: str, x_agent_token: str | None = Header(default=None)):
    authenticate(x_agent_token)
    return browser_focus(slot)


@app.post("/browser/close/{slot}")
def close_browser(slot: str, x_agent_token: str | None = Header(default=None)):
    authenticate(x_agent_token)
    return browser_close(slot)


@app.post("/open-zoom")
def open_zoom_endpoint(x_agent_token: str | None = Header(default=None)):
    authenticate(x_agent_token)
    try:
        return open_zoom("zoom")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Zoom: {type(exc).__name__}: {exc}") from exc


@app.post("/open-schoology")
def open_schoology_endpoint(x_agent_token: str | None = Header(default=None)):
    authenticate(x_agent_token)
    return open_schoology("lausd")


@app.post("/open-schoology-login")
def login_schoology_endpoint(x_agent_token: str | None = Header(default=None)):
    authenticate(x_agent_token)
    return login_schoology("lausd")


@app.post("/school/start")
def start_school_endpoint(x_agent_token: str | None = Header(default=None)):
    authenticate(x_agent_token)
    try:
        return start_school_mode()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"School Mode: {type(exc).__name__}: {exc}") from exc


@app.post("/run-command")
def run_command_endpoint(
    payload: dict[str, Any],
    x_agent_token: str | None = Header(default=None),
):
    authenticate(x_agent_token)
    return run_command(payload)


@app.post("/open-url")
def open_url_endpoint(
    payload: dict[str, Any],
    x_agent_token: str | None = Header(default=None),
):
    authenticate(x_agent_token)
    slot = str(payload.get("slot", "url"))
    return open_url(str(payload.get("url", "")), slot)


@app.post("/input/key")
def input_key(
    payload: dict[str, Any],
    x_agent_token: str | None = Header(default=None),
):
    authenticate(x_agent_token)
    return send_key(payload.get("combo", []))


@app.post("/input/type")
def input_type(
    payload: dict[str, Any],
    x_agent_token: str | None = Header(default=None),
):
    authenticate(x_agent_token)
    return type_text(str(payload.get("text", "")))


@app.post("/unlock")
def unlock_endpoint(x_agent_token: str | None = Header(default=None)):
    authenticate(x_agent_token)
    return unlock_configured()


@app.post("/lock")
def lock_endpoint(x_agent_token: str | None = Header(default=None)):
    authenticate(x_agent_token)
    return lock_pc()


@app.post("/shutdown")
def shutdown_endpoint(x_agent_token: str | None = Header(default=None)):
    authenticate(x_agent_token)
    return shutdown_pc()
