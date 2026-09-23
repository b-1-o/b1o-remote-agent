from fastapi import FastAPI, Header, HTTPException
from .actions import get_status, lock_pc, open_zoom, shutdown_pc
from .config import AGENT_TOKEN

app = FastAPI(title="b1o Remote Agent", version="0.1.0")

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

@app.post("/lock")
def lock_endpoint(x_agent_token: str | None = Header(default=None)):
    authenticate(x_agent_token)
    return lock_pc()

@app.post("/shutdown")
def shutdown_endpoint(x_agent_token: str | None = Header(default=None)):
    authenticate(x_agent_token)
    return shutdown_pc()
