from dotenv import load_dotenv

load_dotenv()

import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
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

    for name in (
        "brave",
        "brave-browser",
        "google-chrome",
        "chromium",
        "chromium-browser",
    ):
        path = shutil.which(name)
        if path:
            return path

    return None


def click_account_email(page) -> bool:
    """Click the account/email choice shown by the LAUSD login page."""
    email = USERNAME.strip()
    if not email:
        return False

    # Prefer an exact visible email, then fall back to accessible/text selectors.
    candidates = [
        page.get_by_text(email, exact=True),
        page.get_by_role("button", name=email),
        page.locator(f'[aria-label="{email}"]'),
    ]

    for candidate in candidates:
        try:
            if candidate.count() > 0 and candidate.first.is_visible():
                candidate.first.click()
                return True
        except Exception:
            continue

    # Some identity pages render the email inside a clickable container.
    try:
        candidate = page.locator(
            "div,button,a"
        ).filter(has_text=email)
        if candidate.count() > 0:
            for index in range(candidate.count()):
                item = candidate.nth(index)
                if item.is_visible():
                    item.click()
                    return True
    except Exception:
        pass

    return False


def fill_password_and_continue(page) -> bool:
    """Fill the password step that appears after choosing the email account."""
    password = page.locator('input[type="password"]')

    try:
        password.first.wait_for(state="visible", timeout=5000)
    except PlaywrightTimeoutError:
        return False

    password.first.fill(PASSWORD)

    button = page.get_by_role(
        "button",
        name=r"(?i)(sign in|log in|login|continue|next|submit)",
    )

    try:
        if button.count() > 0:
            button.first.click()
        else:
            password.first.press("Enter")
    except Exception:
        password.first.press("Enter")

    return True


def login_schoology(page) -> None:
    page.goto(SCHOOLOGY_URL, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)

    # If already signed in, there is nothing to do.
    if page.locator('input[type="password"]').count() == 0:
        try:
            account_clicked = click_account_email(page)
            if account_clicked:
                page.wait_for_timeout(500)
        except Exception:
            pass

    # LAUSD flow: choose the displayed email first, then enter the password.
    if page.locator('input[type="password"]').count() == 0:
        if not click_account_email(page):
            raise RuntimeError(
                "Could not find the Schoology account/email button. "
                "Check B1O_SCHOOLOGY_USER and the page layout."
            )
        page.wait_for_timeout(700)

    if not fill_password_and_continue(page):
        raise RuntimeError(
            "The Schoology password field did not appear after selecting the account."
        )

    page.wait_for_timeout(5000)


def wait_until(hour: int, minute: int) -> None:
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        return

    time.sleep((target - now).total_seconds())


def open_zoom(page) -> None:
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

        login_schoology(page)

        zoom_hour, zoom_minute = (
            int(value) for value in ZOOM_TIME.split(":", 1)
        )
        wait_until(zoom_hour, zoom_minute)

        zoom_page = context.new_page()
        open_zoom(zoom_page)

        zoom_page.bring_to_front()

        while True:
            time.sleep(60)


if __name__ == "__main__":
    main()
