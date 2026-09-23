from dotenv import load_dotenv
load_dotenv()

import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

SCHOOLOGY_HOME = "https://lausdschoology.azurewebsites.net/"
SCHOOLOGY_URL = os.getenv("B1O_SCHOOLOGY_URL", SCHOOLOGY_HOME)
ZOOM_URL = os.getenv("B1O_ZOOM_URL", "")
USERNAME = os.getenv("B1O_SCHOOLOGY_USER", "").strip()
PASSWORD = os.getenv("B1O_SCHOOLOGY_PASSWORD", "")
BROWSER_EXECUTABLE = os.getenv("B1O_BROWSER_EXECUTABLE", "").strip()
PROFILE_DIR = Path(
    os.getenv(
        "B1O_BROWSER_PROFILE",
        "~/.local/share/b1o-remote/browser",
    )
).expanduser()
ZOOM_TIME = os.getenv("B1O_ZOOM_TIME", "08:28")


def browser_path() -> str:
    candidates: list[str] = []

    if BROWSER_EXECUTABLE:
        candidates.append(str(Path(BROWSER_EXECUTABLE).expanduser()))

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

        path = Path(candidate)
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

        version = (result.stdout + result.stderr).lower()
        if "brave" in version:
            return str(path)

    raise RuntimeError(
        "Brave Browser was not found. Set B1O_BROWSER_EXECUTABLE "
        "to the path of Brave (for example /usr/bin/brave)."
    )


def click_students(page) -> None:
    candidates = [
        page.get_by_role("link", name=r"(?i)^students$"),
        page.get_by_role("button", name=r"(?i)^students$"),
        page.get_by_text("Students", exact=True),
    ]

    for candidate in candidates:
        try:
            if candidate.count() > 0 and candidate.first.is_visible():
                candidate.first.click()
                page.wait_for_load_state("domcontentloaded")
                return
        except Exception:
            continue

    raise RuntimeError(
        "Could not find the Students button on the LAUSD Schoology page."
    )


def click_account_tile(page) -> None:
    email = USERNAME

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

    # Microsoft can render the account tile as a button containing the email
    # rather than as a plain text node.
    try:
        candidate = page.locator("div[role='button']").filter(has_text=email)
        for index in range(candidate.count()):
            item = candidate.nth(index)
            if item.is_visible():
                item.click()
                return
    except Exception:
        pass

    # Some sign-in flows skip the tile and show the identifier input directly.
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


def fill_password(page) -> None:
    password = page.locator('input[type="password"]')

    try:
        password.first.wait_for(state="visible", timeout=10000)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(
            "Microsoft login opened, but the password field did not appear."
        ) from exc

    password.first.fill(PASSWORD)

    sign_in = page.get_by_role(
        "button",
        name=r"(?i)^(sign in|next|continue)$",
    )

    if sign_in.count() > 0:
        sign_in.first.click()
    else:
        password.first.press("Enter")


def login_schoology(page) -> None:
    # The LAUSD public page has a Student option. Selecting it starts the
    # district SSO flow, which currently redirects through Microsoft SAML.
    page.goto(SCHOOLOGY_HOME, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)

    click_students(page)
    page.wait_for_timeout(1500)

    click_account_tile(page)
    page.wait_for_timeout(1000)

    fill_password(page)
    page.wait_for_timeout(5000)


def wait_until(hour: int, minute: int) -> None:
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        return
    time.sleep((target - now).total_seconds())


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
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            executable_path=executable,
            headless=False,
            args=[
                "--ozone-platform=wayland",
                "--no-first-run",
            ],
        )

        page = context.pages[0] if context.pages else context.new_page()

        login_schoology(page)

        zoom_hour, zoom_minute = (
            int(value) for value in ZOOM_TIME.split(":", 1)
        )
        wait_until(zoom_hour, zoom_minute)

        zoom_page = context.new_page()
        zoom_page.goto(ZOOM_URL, wait_until="domcontentloaded")
        zoom_page.bring_to_front()

        while True:
            time.sleep(60)


if __name__ == "__main__":
    main()
