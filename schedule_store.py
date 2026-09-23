import json
import re
import tempfile
from pathlib import Path
from typing import Any

from config_store import DATA_DIR

SCHEDULE_FILE = DATA_DIR / "schedules.json"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

def validate(item: dict[str, Any]) -> dict[str, Any]:
    sid = str(item.get("id", "")).strip()
    title = str(item.get("title", "")).strip()
    time_value = str(item.get("time", "")).strip()
    days = item.get("days")
    command_id = str(item.get("command_id", "")).strip()
    enabled = bool(item.get("enabled", True))
    if not ID_RE.fullmatch(sid): raise ValueError("Invalid schedule id")
    if not title or len(title) > 80: raise ValueError("Invalid schedule title")
    if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", time_value): raise ValueError("Invalid time")
    if not isinstance(days, list) or not days: raise ValueError("Days required")
    clean_days = sorted(set(int(x) for x in days))
    if any(x < 0 or x > 6 for x in clean_days): raise ValueError("Invalid day")
    if not command_id: raise ValueError("Command required")
    return {"id": sid, "title": title, "time": time_value, "days": clean_days, "command_id": command_id, "enabled": enabled}

def load_schedules() -> list[dict[str, Any]]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not SCHEDULE_FILE.exists(): return []
    try: data = json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return []
    if not isinstance(data, list): return []
    result = []
    for item in data:
        try: result.append(validate(item))
        except (ValueError, TypeError): pass
    return result

def save_schedules(items: list[dict[str, Any]]) -> None:
    clean = [validate(x) for x in items]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".schedules-", suffix=".json", dir=DATA_DIR)
    try:
        with open(fd, "w", encoding="utf-8", closefd=True) as handle:
            json.dump(clean, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        Path(temp).chmod(0o600)
        Path(temp).replace(SCHEDULE_FILE)
    finally:
        try: Path(temp).unlink()
        except FileNotFoundError: pass

def upsert_schedule(item: dict[str, Any]) -> dict[str, Any]:
    clean = validate(item)
    items = [x for x in load_schedules() if x["id"] != clean["id"]]
    items.append(clean)
    save_schedules(items)
    return clean

def delete_schedule(schedule_id: str) -> bool:
    items = load_schedules()
    new_items = [x for x in items if x["id"] != schedule_id]
    if len(new_items) == len(items): return False
    save_schedules(new_items)
    return True