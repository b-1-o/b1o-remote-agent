from __future__ import annotations

import queue
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from config_store import load_settings


def _browser_path(settings: dict) -> str:
    import shutil
    import subprocess

    configured = str(settings.get("browser", "")).strip()
    candidates = [configured] if configured else []
    for name in ("brave", "brave-browser"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    candidates.extend([
        "/usr/bin/brave",
        "/usr/bin/brave-browser",
        "/opt/brave.com/brave/brave",
    ])

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

    raise RuntimeError("Brave Browser was not found.")


def _click_account_tile(page, email: str) -> None:
    candidates = [
        page.get_by_text(email, exact=True),
        page.get_by_role("button", name=email),
        page.locator(f'[aria-label="{email}"]'),
        page.locator(f'[data-test-id*="tile"]').filter(has_text=email),
    ]

    for candidate in candidates:
        try:
            if candidate.count() and candidate.first.is_visible():
                candidate.first.click()
                return
        except Exception:
            continue

    identifier = page.locator(
        'input[type="email"], input[name="loginfmt"], input[name="identifier"]'
    )
    if identifier.count() and identifier.first.is_visible():
        identifier.first.fill(email)
        button = page.get_by_role(
            "button",
            name=re.compile(r"^(next|sign in)$", re.I),
        )
        if button.count():
            button.first.click()
        else:
            identifier.first.press("Enter")
        return

    raise RuntimeError("Could not find the LAUSD/Microsoft account selector.")


def _fill_password(page, password: str) -> None:
    field = page.locator('input[type="password"]')
    field.first.wait_for(state="visible", timeout=15000)
    field.first.fill(password)
    button = page.get_by_role(
        "button",
        name=re.compile(r"^(sign in|next|continue)$", re.I),
    )
    if button.count():
        button.first.click()
    else:
        field.first.press("Enter")


@dataclass
class _Job:
    fn: Callable[[], Any]
    event: threading.Event
    box: dict[str, Any]


class BrowserManager:
    """Single Brave/Playwright owner for all remote browser tabs."""

    def __init__(self) -> None:
        self._jobs: queue.Queue[_Job] = queue.Queue()
        self._thread = threading.Thread(
            target=self._worker,
            name="b1o-browser-manager",
            daemon=True,
        )
        self._started = False
        self._start_lock = threading.Lock()
        self._tabs: dict[str, Any] = {}
        self._zoom_chat: deque[dict[str, str]] = deque(maxlen=100)
        self._zoom_seen: set[str] = set()
        self._school_timer: threading.Timer | None = None
        self._pw = None
        self._context = None

    def _ensure_started(self) -> None:
        with self._start_lock:
            if self._started:
                return
            self._started = True
            self._thread.start()

    def call(self, fn: Callable[[], Any]) -> Any:
        self._ensure_started()
        event = threading.Event()
        box: dict[str, Any] = {}
        self._jobs.put(_Job(fn=fn, event=event, box=box))
        event.wait(timeout=45)
        if not event.is_set():
            raise RuntimeError("Browser manager timed out")
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def _worker(self) -> None:
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as pw:
                self._pw = pw
                self._start_browser()
                self._run_queue()
        except Exception:
            self._pw = None
            self._context = None

    def _start_browser(self) -> None:
        settings = load_settings()
        executable = _browser_path(settings)
        profile = Path(
            str(settings.get(
                "browser_profile",
                "~/.local/share/b1o-remote/browser",
            ))
        ).expanduser()
        profile.mkdir(parents=True, exist_ok=True)

        self._context = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            executable_path=executable,
            headless=False,
            args=[
                "--ozone-platform=wayland",
                "--no-first-run",
                "--disable-session-crashed-bubble",
            ],
        )

        # Existing tabs from our profile are retained and indexed later.
        for index, page in enumerate(self._context.pages):
            if not page.is_closed():
                self._tabs.setdefault(f"existing_{index}", page)

    def _run_queue(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                self._cleanup_tabs()
                if self._context is None:
                    self._start_browser()
                job.box["result"] = job.fn()
            except Exception as exc:
                job.box["error"] = exc
            finally:
                job.event.set()
                self._jobs.task_done()

    def _cleanup_tabs(self) -> None:
        dead = [
            slot for slot, page in self._tabs.items()
            if page is None or page.is_closed()
        ]
        for slot in dead:
            self._tabs.pop(slot, None)

    def _new_page(self, slot: str):
        self._cleanup_tabs()
        page = self._tabs.get(slot)
        if page is not None and not page.is_closed():
            return page

        page = self._context.new_page()
        self._tabs[slot] = page
        return page

    def _open_slot(self, slot: str, url: str):
        page = self._new_page(slot)
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.bring_to_front()
        return page

    def _focus_slot(self, slot: str) -> bool:
        self._cleanup_tabs()
        page = self._tabs.get(slot)
        if page is None or page.is_closed():
            return False
        page.bring_to_front()
        return True

    def open_url(self, slot: str, url: str) -> dict:
        if not (url.startswith("https://") or url.startswith("http://")):
            raise ValueError("Only http/https URLs are allowed")

        def job() -> dict:
            page = self._new_page(slot)
            reused = bool(page.url and page.url != "about:blank")
            if page.url != url:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.bring_to_front()
            return {
                "success": True,
                "action": "open_url",
                "slot": slot,
                "url": page.url,
                "reused": reused,
            }

        return self.call(job)

    def open_zoom(self, slot: str = "zoom") -> dict:
        settings = load_settings()
        url = str(settings.get("zoom_url", "")).strip()
        if not url:
            raise RuntimeError("Zoom URL is not configured")
        result = self.open_url(slot, url)
        try:
            self.call(lambda: self._open_zoom_chat_panel())
        except Exception:
            pass
        return result

    def _open_zoom_chat_panel(self) -> None:
        self._cleanup_tabs()
        page = self._tabs.get("zoom")
        if page is None or page.is_closed():
            return

        buttons = page.get_by_role(
            "button",
            name=re.compile(r"\bchat\b", re.I),
        )
        for index in range(min(buttons.count(), 5)):
            button = buttons.nth(index)
            try:
                if button.is_visible():
                    button.click()
                    return
            except Exception:
                continue

    def open_schoology(self, slot: str = "lausd") -> dict:
        settings = load_settings()
        url = str(settings.get("schoology_url", "")).strip()
        if not url:
            raise RuntimeError("Schoology URL is not configured")
        return self.open_url(slot, url)

    def login_schoology(self, slot: str = "lausd") -> dict:
        settings = load_settings()
        user = str(settings.get("schoology_user", "")).strip()
        password = str(settings.get("schoology_password", ""))
        login_url = str(settings.get("schoology_url", "")).strip()

        if not user or not password:
            raise RuntimeError("Schoology credentials are not configured in Admin.")
        if not login_url:
            raise RuntimeError("Schoology Student Login URL is not configured.")

        def job() -> dict:
            page = self._new_page(slot)
            page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)

            current = page.url.lower()
            if "schoology" in current and "student/login" not in current and "login" not in current:
                page.bring_to_front()
                return {
                    "success": True,
                    "action": "schoology_login",
                    "slot": slot,
                    "already_logged_in": True,
                    "url": page.url,
                }

            _click_account_tile(page, user)
            page.wait_for_timeout(1200)
            _fill_password(page, password)
            page.wait_for_timeout(5000)
            page.bring_to_front()

            return {
                "success": True,
                "action": "schoology_login",
                "slot": slot,
                "already_logged_in": False,
                "url": page.url,
            }

        return self.call(job)

    def send_key(self, slot: str, combo: list[str]) -> dict:
        if not combo:
            raise ValueError("Empty key combo")

        def job() -> dict:
            page = self._new_page(slot)
            page.bring_to_front()
            parts = [str(item).strip().upper() for item in combo]
            key = "+".join({
                "CTRL": "Control",
                "ALT": "Alt",
                "SHIFT": "Shift",
                "SUPER": "Meta",
                "ENTER": "Enter",
                "ESC": "Escape",
                "TAB": "Tab",
                "SPACE": " ",
                "BACKSPACE": "Backspace",
                "LEFT": "ArrowLeft",
                "RIGHT": "ArrowRight",
                "UP": "ArrowUp",
                "DOWN": "ArrowDown",
            }.get(part, part.title()) for part in parts)
            page.keyboard.press(key)
            return {"success": True, "action": "key", "slot": slot, "combo": parts}

        return self.call(job)

    def type_text(self, slot: str, value: str) -> dict:
        def job() -> dict:
            page = self._new_page(slot)
            page.bring_to_front()
            page.keyboard.type(value)
            return {"success": True, "action": "type", "slot": slot, "length": len(value)}

        return self.call(job)

    def start_school_mode(self) -> dict:
        result = self.login_schoology("lausd")

        settings = load_settings()
        zoom_time = str(settings.get("zoom_time", "08:30"))
        try:
            hour, minute = (int(part) for part in zoom_time.split(":", 1))
        except ValueError as exc:
            raise RuntimeError("Invalid Zoom time") from exc

        now = time.localtime()
        target = time.mktime((
            now.tm_year,
            now.tm_mon,
            now.tm_mday,
            hour,
            minute,
            0,
            0,
            0,
            -1,
        ))
        delay = max(0.0, target - time.time())

        if self._school_timer is not None:
            self._school_timer.cancel()

        if delay <= 0:
            self.open_zoom("zoom")
            self._school_timer = None
        else:
            self._school_timer = threading.Timer(
                delay,
                lambda: self.open_zoom("zoom"),
            )
            self._school_timer.daemon = True
            self._school_timer.start()

        return {
            "success": True,
            "action": "school_mode",
            "lausd": result,
            "zoom_scheduled_in": round(delay),
        }

    def close_slot(self, slot: str) -> dict:
        def job() -> dict:
            page = self._tabs.get(slot)
            if page is not None and not page.is_closed():
                page.close()
            self._tabs.pop(slot, None)
            return {"success": True, "action": "close", "slot": slot}

        return self.call(job)

    def focus_slot(self, slot: str) -> dict:
        def job() -> dict:
            found = self._focus_slot(slot)
            if not found:
                raise RuntimeError(f"Browser tab '{slot}' is not open")
            return {"success": True, "action": "focus", "slot": slot}

        return self.call(job)

    def tabs(self) -> list[dict[str, Any]]:
        def job() -> list[dict[str, Any]]:
            self._cleanup_tabs()
            result = []
            for slot, page in self._tabs.items():
                if page is None or page.is_closed():
                    continue
                result.append({
                    "slot": slot,
                    "url": page.url,
                    "title": page.title(),
                    "open": True,
                })
            return result

        return self.call(job)

    def _collect_zoom_chat_on_page(self, page) -> list[dict[str, str]]:
        selectors = [
            '[role="log"] [role="listitem"]',
            '[aria-live="polite"] [role="listitem"]',
            '[data-testid*="chat" i] [role="listitem"]',
            '[data-testid*="chat-message" i]',
        ]

        nodes = []
        for selector in selectors:
            try:
                count = page.locator(selector).count()
                for index in range(min(count, 100)):
                    nodes.append(page.locator(selector).nth(index))
            except Exception:
                continue

        messages = []
        for node in nodes:
            try:
                if not node.is_visible():
                    continue
                text = node.inner_text().strip()
                if not text:
                    continue
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                if not lines:
                    continue
                key = "\n".join(lines)
                if key in self._zoom_seen:
                    continue
                self._zoom_seen.add(key)
                messages.append({
                    "text": " ".join(lines),
                    "time": time.strftime("%H:%M:%S"),
                })
            except Exception:
                continue

        self._zoom_chat.extend(messages)
        return messages

    def zoom_chat(self) -> dict[str, Any]:
        def job() -> dict[str, Any]:
            self._cleanup_tabs()
            page = self._tabs.get("zoom")
            if page is None or page.is_closed():
                return {"open": False, "messages": []}
            messages = self._collect_zoom_chat_on_page(page)
            return {
                "open": True,
                "messages": list(self._zoom_chat),
                "new_messages": messages,
            }

        return self.call(job)


_BROWSER = BrowserManager()


def browser_manager() -> BrowserManager:
    return _BROWSER
