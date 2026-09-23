import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

SCHOOLOGY_URL = os.getenv(
    "B1O_SCHOOLOGY_URL",
    "https://lausdschoology.azurewebsites.net/en-US/Student/Login",
)
ZOOM_URL = os.getenv("B1O_ZOOM_URL", "")
USERNAME = os.getenv("B1O_SCHOOLOGY_USER", "")
PASSWORD = os.getenv("B1O_SCHOOLOGY_PASSWORD", "")
BROWSER_EXECUTABLE = os.getenv("B1O_BROWSER_EXECUTABLE", "")
PROFILE_DIR = Path(
    os.getenv(
        "B1O_BROWSER_PROFILE",
        "~/.local/share/b1o-remote/browser",
    )
).expanduser()
ZOOM_TIME = os.getenv("B1O_ZOOM_TIME", "08:28")


def browser_path() -> str | None:
    if BROWSER_EXECUTABLE:
        return BROWSER_EXECUTABLE
    for name in ("brave", "brave-browser", "google-chrome", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    return None


def fill_login(page) -> bool:
    password_inputs = page.locator('input[type="password"]')
    if password_inputs.count() == 0:
        return False

    text_inputs = page.locator(
        'input:not([type="hidden"]):not([type="password"]):not([type="submit"])'
    )

    password_inputs.first.fill(PASSWORD)

    if text_inputs.count() > 0:
        text_inputs.first.fill(USERNAME)

    button = page.get_by_role(
        "button",
        name=r"(?i)(sign in|log in|login|continue|submit)",
    )
    if button.count() > 0:
        button.first.click()
    else:
        page.keyboard.press("Enter")

    return True


def wait_until(hour: int, minute: int) -> None:
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        return
    time.sleep((target - now).total_seconds())


def open_zoom(page) -> None:
    if not ZOOM_URL:
        return
    page.goto(ZOOM_URL, wait_until="domcontentloaded")


def main() -> None:
    if not USERNAME or not PASSWORD:
        raise RuntimeError(
            "Set B1O_SCHOOLOGY_USER and B1O_SCHOOLOGY_PASSWORD in .env"
        )
    if not ZOOM_URL:
        raise RuntimeError("Set B1O_ZOOM_URL in .env")

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    executable = browser_path()

    with sync_playwright() as pw:
        launch_args = {
            "user_data_dir": str(PROFILE_DIR),
            "headless": False,
            "args": ["--ozone-platform=wayland"],
        }
        if executable:
            launch_args["executable_path"] = executable

        context = pw.chromium.launch_persistent_context(**launch_args)
        page = context.pages[0] if context.pages else context.new_page()

        page.goto(SCHOOLOGY_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        # First run: fill the Schoology login form. Later runs may reuse
        # the persistent browser session if the school keeps the session alive.
        if "login" in page.url.lower() or page.locator('input[type="password"]').count():
            if not fill_login(page):
                raise RuntimeError("Could not find the Schoology login form")
            page.wait_for_timeout(5000)

        zoom_hour, zoom_minute = (int(v) for v in ZOOM_TIME.split(":", 1))
        wait_until(zoom_hour, zoom_minute)

        zoom_page = context.new_page()
        open_zoom(zoom_page)

        # Keep the browser open for the class.
        context.pages[0].bring_to_front()
        while True:
            time.sleep(60)


if __name__ == "__main__":
    main()
