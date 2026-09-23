import json
import os
import tempfile
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.getenv(
    "B1O_DATA_DIR",
    "~/.local/share/b1o-remote",
)).expanduser()
SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULTS: dict[str, Any] = {
    "school_enabled": True,
    "school_days": [0, 1, 2, 3, 4],
    "school_time": "08:20",
    "zoom_time": "08:30",
    "schoology_url": "https://lausdschoology.azurewebsites.net/en-US/Student/Login",
    "schoology_user": "eghabuzy0001@mymail.lausd.net",
    "schoology_password": "",
    "zoom_url": "https://lausd.zoom.us/j/4483525320",
    "browser": "/usr/bin/brave",
    "browser_profile": "~/.local/share/b1o-remote/browser",
    "pc_unlock_password": "",
}


def _initial_settings() -> dict[str, Any]:
    values = DEFAULTS.copy()

    env_map = {
        "schoology_url": "B1O_SCHOOLOGY_URL",
        "schoology_user": "B1O_SCHOOLOGY_USER",
        "schoology_password": "B1O_SCHOOLOGY_PASSWORD",
        "zoom_url": "B1O_ZOOM_URL",
        "browser": "B1O_BROWSER_EXECUTABLE",
        "browser_profile": "B1O_BROWSER_PROFILE",
        "school_time": "B1O_SCHOOL_TIME",
        "zoom_time": "B1O_ZOOM_TIME",
    }

    for key, env_name in env_map.items():
        value = os.getenv(env_name)
        if value:
            values[key] = value

    return values


def _ensure_file() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not SETTINGS_FILE.exists():
        save_settings(_initial_settings())
        return

    try:
        current = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        current = {}

    defaults = _initial_settings()
    changed = False

    for key, value in defaults.items():
        if key not in current or current[key] in ("", None):
            current[key] = value
            changed = True

    if changed:
        save_settings(current)


def load_settings() -> dict[str, Any]:
    _ensure_file()

    with SETTINGS_FILE.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    result = DEFAULTS.copy()
    result.update(data)
    return result


def save_settings(settings: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    fd, temp_name = tempfile.mkstemp(
        prefix=".settings-",
        suffix=".json",
        dir=DATA_DIR,
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(settings, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

        os.chmod(temp_name, 0o600)
        os.replace(temp_name, SETTINGS_FILE)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def update_setting(key: str, value: Any) -> dict[str, Any]:
    settings = load_settings()
    if key not in DEFAULTS:
        raise KeyError(key)

    settings[key] = value
    save_settings(settings)
    return settings
