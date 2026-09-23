import json
import re
import tempfile
from pathlib import Path
from typing import Any

from config_store import DATA_DIR

COMMANDS_DIR = DATA_DIR / "commands"
COMMAND_ID = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")
ALLOWED_ACTIONS = {"open_url", "key", "type", "open_zoom", "open_schoology"}


def _validate_command(item: dict[str, Any]) -> dict[str, Any]:
    command_id = str(item.get("id", "")).strip()
    title = str(item.get("title", "")).strip()
    actions = item.get("actions")

    if not COMMAND_ID.fullmatch(command_id):
        raise ValueError("Invalid command id")

    if not title or len(title) > 80:
        raise ValueError("Invalid command title")

    if not isinstance(actions, list) or not actions or len(actions) > 20:
        raise ValueError("Invalid actions list")

    clean_actions = []
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("Action must be an object")

        action_type = action.get("type")
        if action_type not in ALLOWED_ACTIONS:
            raise ValueError(f"Unsupported action: {action_type}")

        if action_type == "open_url":
            url = str(action.get("url", "")).strip()
            if not (url.startswith("https://") or url.startswith("http://")):
                raise ValueError("open_url requires http/https URL")
            clean_actions.append({"type": action_type, "url": url})

        elif action_type == "key":
            combo = action.get("combo")
            if not isinstance(combo, list) or not combo:
                raise ValueError("key requires combo list")
            clean_actions.append({
                "type": action_type,
                "combo": [str(key).upper() for key in combo],
            })

        elif action_type == "type":
            text = str(action.get("text", ""))
            if len(text) > 5000:
                raise ValueError("type text is too long")
            clean_actions.append({"type": action_type, "text": text})

        else:
            clean_actions.append({"type": action_type})

    return {
        "id": command_id,
        "title": title,
        "actions": clean_actions,
    }


def load_commands() -> list[dict[str, Any]]:
    COMMANDS_DIR.mkdir(parents=True, exist_ok=True)
    result = []

    for path in sorted(COMMANDS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items = data.get("commands", [data]) if isinstance(data, dict) else data
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict):
                    try:
                        result.append(_validate_command(item))
                    except ValueError:
                        continue
        except (OSError, json.JSONDecodeError):
            continue

    return result


def install_pack(content: bytes, filename: str) -> list[dict[str, Any]]:
    if len(content) > 64 * 1024:
        raise ValueError("Command pack is too large")

    if not filename.lower().endswith(".json"):
        raise ValueError("Only JSON command packs are supported")

    data = json.loads(content.decode("utf-8"))
    items = data.get("commands") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise ValueError("No commands found")

    commands = [_validate_command(item) for item in items]

    COMMANDS_DIR.mkdir(parents=True, exist_ok=True)
    for command in commands:
        path = COMMANDS_DIR / f"{command['id']}.json"
        fd, temp = tempfile.mkstemp(
            prefix=f".{command['id']}-",
            suffix=".json",
            dir=COMMANDS_DIR,
        )
        with open(fd, "w", encoding="utf-8", closefd=True) as handle:
            json.dump(command, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        Path(temp).replace(path)

    return commands
