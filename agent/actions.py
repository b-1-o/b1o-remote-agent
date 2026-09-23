import subprocess
import time
from pathlib import Path

from config_store import load_settings
from .config import AGENT_TOKEN

_OPEN_GUARD: dict[str, float] = {}
_OPEN_GUARD_SECONDS = 4.0


def _spawn(command: list[str]) -> None:
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _browser_command(url: str) -> list[str]:
    settings = load_settings()
    browser = str(settings.get("browser", "/usr/bin/brave")).strip()

    # Regular remote buttons use the user's normal Brave profile.
    # School automation has its own dedicated Playwright profile.
    return [
        browser,
        "--new-tab",
        url,
    ]


def get_status() -> dict:
    hostname = subprocess.check_output(["hostname"], text=True).strip()
    return {"online": True, "hostname": hostname}


def open_url(url: str) -> dict:
    if not (url.startswith("https://") or url.startswith("http://")):
        raise ValueError("Only http/https URLs are allowed")

    # Prevent accidental double/triple launches from repeated Telegram callbacks,
    # browser retries, or a quick double-click.
    now = time.monotonic()
    last = _OPEN_GUARD.get(url, 0.0)
    if now - last < _OPEN_GUARD_SECONDS:
        return {"success": True, "action": "open_url", "deduplicated": True}

    _OPEN_GUARD[url] = now
    _spawn(_browser_command(url))
    return {"success": True, "action": "open_url"}


def open_zoom() -> dict:
    settings = load_settings()
    url = str(settings.get("zoom_url", "")).strip()
    if not url:
        raise RuntimeError("Zoom URL is not configured")
    return open_url(url)


def open_schoology() -> dict:
    settings = load_settings()
    url = str(settings.get("schoology_url", "")).strip()
    if not url:
        raise RuntimeError("Schoology URL is not configured")
    return open_url(url)


def lock_pc() -> dict:
    _spawn(["loginctl", "lock-session"])
    return {"success": True, "action": "lock"}


def shutdown_pc() -> dict:
    _spawn(["systemctl", "poweroff"])
    return {"success": True, "action": "shutdown"}


def unlock_session() -> dict:
    username = subprocess.check_output(["id", "-un"], text=True).strip()
    sessions = subprocess.check_output(
        ["loginctl", "list-sessions", "--no-legend"],
        text=True,
    ).splitlines()

    unlocked = []

    for line in sessions:
        parts = line.split()
        if len(parts) < 3 or parts[2] != username:
            continue

        session_id = parts[0]
        result = subprocess.run(
            ["loginctl", "unlock-session", session_id],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            unlocked.append(session_id)

    return {
        "success": bool(unlocked),
        "action": "unlock",
        "sessions": unlocked,
    }
