import os
import threading
import time
from datetime import datetime

import httpx
from config_store import load_settings

AGENT_URL = os.getenv("B1O_AGENT_URL", "http://127.0.0.1:8765")
AGENT_TOKEN = os.getenv("B1O_REMOTE_TOKEN", "")


def _agent_post(path: str, payload: dict | None = None) -> dict:
    response = httpx.post(
        AGENT_URL + path,
        json=payload,
        headers={"X-Agent-Token": AGENT_TOKEN},
        timeout=60,
    )
    if not response.is_success:
        raise RuntimeError(
            f"Agent HTTP {response.status_code}: {response.text[:300]}"
        )
    return response.json()


def open_school_session() -> dict:
    return _agent_post("/school/start")


def open_schoology_session() -> dict:
    return _agent_post("/open-schoology-login")


def should_run_today(settings: dict, now: datetime) -> bool:
    return (
        bool(settings.get("school_enabled", True))
        and now.weekday() in settings.get("school_days", [0, 1, 2, 3, 4])
    )


def time_matches(value: str, now: datetime) -> bool:
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
    except (ValueError, TypeError):
        return False
    return now.hour == hour and now.minute == minute


def scheduler_loop() -> None:
    from commands_store import load_commands
    from schedule_store import load_schedules

    fired: set[tuple[str, str]] = set()
    school_started: set[str] = set()

    while True:
        now = datetime.now()
        day = now.date().isoformat()
        settings = load_settings()

        if (
            should_run_today(settings, now)
            and time_matches(str(settings.get("school_time", "08:20")), now)
            and day not in school_started
        ):
            school_started.add(day)
            try:
                open_school_session()
            except Exception as exc:
                print(f"School Mode error: {type(exc).__name__}: {exc}")

        commands = {item["id"]: item for item in load_commands()}

        for schedule in load_schedules():
            if not schedule["enabled"]:
                continue

            key = (day, schedule["id"])
            if now.weekday() not in schedule["days"]:
                continue
            if not time_matches(schedule["time"], now):
                continue
            if key in fired:
                continue

            command = commands.get(schedule["command_id"])
            if command is None:
                continue

            fired.add(key)
            try:
                _agent_post("/run-command", command)
            except Exception as exc:
                print(
                    f"Schedule {schedule['id']} error: "
                    f"{type(exc).__name__}: {exc}"
                )

        time.sleep(20)


def main() -> None:
    scheduler_loop()


if __name__ == "__main__":
    main()
