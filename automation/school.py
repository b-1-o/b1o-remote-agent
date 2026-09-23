import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from config_store import load_settings

_SCHOOL_SESSION_RUNNING = False



def browser_path(settings: dict) -> str:
    configured = str(settings.get("browser", "")).strip()
    candidates = [configured] if configured else []

    for name in ("brave", "brave-browser"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    candidates.extend(
        [
            "/usr/bin/brave",
            "/usr/bin/brave-browser",
            "/opt/brave.com/brave/brave",
        ]
    )

    seen: set[str] = set()

    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)

        path = Path(candidate).expanduser()
        if not path.is_file():
            continue

        try:
            result = subprocess.run(
                [str(path), "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            continue

        if "brave" in (result.stdout + result.stderr).lower():
            return str(path)

    raise RuntimeError(
        "Brave Browser was not found. Configure it from Telegram settings."
    )


def click_account_tile(page, email: str) -> None:
    candidates = [
        page.get_by_text(email, exact=True),
        page.get_by_role("button", name=email),
        page.locator(f'[aria-label="{email}"]'),
        page.locator(f'[data-test-id*="tile"]').filter(has_text=email),
    ]

    for candidate in candidates:
        try:
            if candidate.count() > 0 and candidate.first.is_visible():
                candidate.first.click()
                return
        except Exception:
            continue

    try:
        candidate = page.locator("div[role='button']").filter(has_text=email)
        for index in range(candidate.count()):
            item = candidate.nth(index)
            if item.is_visible():
                item.click()
                return
    except Exception:
        pass

    identifier = page.locator(
        'input[type="email"], input[name="loginfmt"], input[name="identifier"]'
    )

    if identifier.count() > 0 and identifier.first.is_visible():
        identifier.first.fill(email)
        next_button = page.get_by_role(
            "button",
            name=r"(?i)^(next|sign in)$",
        )

        if next_button.count() > 0:
            next_button.first.click()
        else:
            identifier.first.press("Enter")
        return

    raise RuntimeError(
        "Could not find the LAUSD/Microsoft account tile for the configured email."
    )


def fill_password(page, password_value: str) -> None:
    password = page.locator('input[type="password"]')

    try:
        password.first.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(
            "The password field did not appear after selecting the account."
        ) from exc

    password.first.fill(password_value)

    sign_in = page.get_by_role(
        "button",
        name=r"(?i)^(sign in|next|continue)$",
    )

    if sign_in.count() > 0:
        sign_in.first.click()
    else:
        password.first.press("Enter")


def login_schoology(page, settings: dict) -> None:
    user = str(settings.get("schoology_user", "")).strip()
    password = str(settings.get("schoology_password", ""))

    if not user or not password:
        raise RuntimeError(
            "Schoology email/password are not configured. Open Telegram → Settings."
        )

    login_url = str(settings.get("schoology_url", "")).strip()
    if not login_url:
        raise RuntimeError("Schoology Student Login URL is not configured.")

    page.goto(login_url, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    click_account_tile(page, user)
    page.wait_for_timeout(1000)
    fill_password(page, password)
    page.wait_for_timeout(5000)


def open_school_session() -> None:
    global _SCHOOL_SESSION_RUNNING

    if _SCHOOL_SESSION_RUNNING:
        return

    _SCHOOL_SESSION_RUNNING = True
    try:
        _open_school_session()
    finally:
        _SCHOOL_SESSION_RUNNING = False


def _open_school_session() -> None:
    settings = load_settings()

    executable = browser_path(settings)
    profile_dir = Path(
        str(settings["browser_profile"])
    ).expanduser()
    profile_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            executable_path=executable,
            headless=False,
            args=[
                "--ozone-platform=wayland",
                "--no-first-run",
            ],
        )

        page = context.pages[0] if context.pages else context.new_page()
        login_schoology(page, settings)

        zoom_url = str(settings.get("zoom_url", "")).strip()
        if zoom_url:
            zoom_hour, zoom_minute = (
                int(value) for value in settings["zoom_time"].split(":", 1)
            )
            wait_until(zoom_hour, zoom_minute)

            zoom_page = context.new_page()
            zoom_page.goto(zoom_url, wait_until="domcontentloaded")
            zoom_page.bring_to_front()

        while True:
            time.sleep(60)


def wait_until(hour: int, minute: int) -> None:
    now = datetime.now()
    target = now.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )

    if target <= now:
        return

    time.sleep((target - now).total_seconds())


def should_run_today(settings: dict, now: datetime) -> bool:
    return (
        bool(settings.get("school_enabled", True))
        and now.weekday() in settings.get("school_days", [0, 1, 2, 3, 4])
    )

def time_matches(value: str, now: datetime) -> bool:
    try: hour, minute = (int(part) for part in value.split(":", 1))
    except (ValueError, TypeError): return False
    return now.hour == hour and now.minute == minute

def scheduler_loop() -> None:
    from commands_store import load_commands
    from runner import execute_command_sync
    from schedule_store import load_schedules
    import threading

    fired: set[tuple[str, str]] = set()
    school_started: set[str] = set()

    while True:
        now = datetime.now()
        day = now.date().isoformat()
        settings = load_settings()

        if should_run_today(settings, now) and time_matches(settings["school_time"], now) and day not in school_started:
            school_started.add(day)
            threading.Thread(target=open_school_session, daemon=True).start()

        commands = {x["id"]: x for x in load_commands()}
        for schedule in load_schedules():
            if not schedule["enabled"]: continue
            key = (day, schedule["id"])
            if now.weekday() not in schedule["days"]: continue
            if not time_matches(schedule["time"], now): continue
            if key in fired: continue
            command = commands.get(schedule["command_id"])
            if command is None: continue
            fired.add(key)
            try:
                threading.Thread(target=execute_command_sync, args=(command,), daemon=True).start()
            except Exception as exc:
                print(f"Schedule error: {type(exc).__name__}: {exc}")

        time.sleep(20)
def main() -> None:
    scheduler_loop()


if __name__ == "__main__":
    main()
