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
from automation.school import browser_path, click_account_tile, fill_password


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

        while True:
            try:
                self._jobs.get()
                # Requeue through a tiny wrapper so browser initialization and
                # the actual job always happen on this same thread.
                job = self._jobs.task_done
            except Exception:
                continue

            # The queue item is retrieved again using a dedicated internal path.
            # This branch is replaced below by _run_queue for clarity.
            break

        # Re-enter the real worker loop.
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
        executable = browser_path(settings)
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
            if page.url != url:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.bring_to_front()
            return {
                "success": True,
                "action": "open_url",
                "slot": slot,
                "url": page.url,
                "reused": page.url == url,
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

            click_account_tile(page, user)
            page.wait_for_timeout(1200)
            fill_password(page, password)
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
