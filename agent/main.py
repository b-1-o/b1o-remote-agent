from typing import Any

from fastapi import FastAPI, Header, HTTPException

from .actions import (
    get_status,
    lock_pc,
    open_schoology,
    open_url,
    open_zoom,
    shutdown_pc,
)
from .config import AGENT_TOKEN
from .input_actions import type_text, unlock_with_password, send_key

app = FastAPI(title="b1o Remote Agent", version="0.2.0")


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


@app.post("/open-zoom")
def open_zoom_endpoint(x_agent_token: str | None = Header(default=None)):
    authenticate(x_agent_token)
    return open_zoom()


@app.post("/open-schoology")
def open_schoology_endpoint(x_agent_token: str | None = Header(default=None)):
    authenticate(x_agent_token)
    return open_schoology()


@app.post("/open-url")
def open_url_endpoint(
    payload: dict[str, Any],
    x_agent_token: str | None = Header(default=None),
):
    authenticate(x_agent_token)
    return open_url(str(payload.get("url", "")))


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


@app.post("/unlock-password")
def unlock_password(
    payload: dict[str, Any],
    x_agent_token: str | None = Header(default=None),
):
    authenticate(x_agent_token)
    password = str(payload.get("password", ""))
    return unlock_with_password(password)


@app.post("/lock")
def lock_endpoint(x_agent_token: str | None = Header(default=None)):
    authenticate(x_agent_token)
    return lock_pc()


@app.post("/shutdown")
def shutdown_endpoint(x_agent_token: str | None = Header(default=None)):
    authenticate(x_agent_token)
    return shutdown_pc()
