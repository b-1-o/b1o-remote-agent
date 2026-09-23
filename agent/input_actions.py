import shutil
import subprocess
from typing import Iterable


KEY_CODES = {
    "ENTER": "28",
    "ESC": "1",
    "TAB": "15",
    "SPACE": "57",
    "BACKSPACE": "14",
    "LEFT": "105",
    "RIGHT": "106",
    "UP": "103",
    "DOWN": "108",
    "CTRL": "29",
    "ALT": "56",
    "SHIFT": "42",
    "SUPER": "125",
    "L": "38",
    "R": "19",
    "C": "46",
    "V": "47",
    "X": "45",
    "A": "30",
}


def _ydotool() -> str:
    path = shutil.which("ydotool")
    if not path:
        raise RuntimeError(
            "ydotool is not installed. Install/configure it before using remote keyboard input."
        )
    return path


def _run(args: list[str]) -> None:
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Input command failed")


def send_key(combo: Iterable[str]) -> dict:
    tool = _ydotool()
    names = [str(item).strip().upper() for item in combo]
    if not names or any(name not in KEY_CODES for name in names):
        raise ValueError("Unsupported key in combo")

    events: list[str] = []
    for name in names:
        code = KEY_CODES[name]
        events.extend([f"{code}:1", f"{code}:0"])

    _run([tool, "key", *events])
    return {"success": True, "action": "key", "combo": names}


def type_text(value: str) -> dict:
    if not value:
        return {"success": True, "action": "type", "length": 0}

    tool = _ydotool()
    _run([tool, "type", "--key-delay", "5", value])
    return {"success": True, "action": "type", "length": len(value)}


def unlock_with_password(password: str) -> dict:
    if not password:
        raise ValueError("Empty password")

    result = type_text(password)
    send_key(["ENTER"])
    result.update({"action": "unlock", "password_used": True})
    return result


def unlock_configured() -> dict:
    from config_store import load_settings

    password = str(load_settings().get("pc_unlock_password", ""))
    if not password:
        raise RuntimeError("PC unlock password is not configured in Admin.")
    return unlock_with_password(password)
