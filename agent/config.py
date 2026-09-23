import os

HOST = os.getenv("B1O_AGENT_HOST", "127.0.0.1")
PORT = int(os.getenv("B1O_AGENT_PORT", "8765"))
AGENT_TOKEN = os.getenv("B1O_REMOTE_TOKEN", "")
ZOOM_URL = os.getenv("B1O_ZOOM_URL", "")

if not AGENT_TOKEN:
    raise RuntimeError("B1O_REMOTE_TOKEN is not configured")
if not ZOOM_URL:
    raise RuntimeError("B1O_ZOOM_URL is not configured")
