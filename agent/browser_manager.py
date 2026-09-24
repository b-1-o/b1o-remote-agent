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
        self._browser = None
        self._context = None
        self._fatal_error: Exception | None = None

    def _ensure_started(self) -> None:
        with self._start_lock:
            if self._started and self._thread.is_alive():
                return
            if self._started and not self._thread.is_alive():
                self._started = False
                self._jobs = queue.Queue()
                self._thread = threading.Thread(
                    target=self._worker,
                    name="b1o-browser-manager",
                    daemon=True,
                )
            self._fatal_error = None
            self._started = True
            self._thread.start()

    def call(self, fn: Callable[[], Any]) -> Any:
        self._ensure_started()
        event = threading.Event()
        box: dict[str, Any] = {}
        self._jobs.put(_Job(fn=fn, event=event, box=box))
        event.wait(timeout=90)
        if not event.is_set():
            detail = self._fatal_error
            if detail:
                raise RuntimeError(
                    f"Browser manager stopped: {type(detail).__name__}: {detail}"
                ) from detail
            raise RuntimeError("Browser manager timed out after 90 seconds")
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def _worker(self) -> None:
        from playwright.sync_api import sync_playwright

        try:
            with sync_playwright() as pw:
                self._pw = pw
                # Browser startup happens inside _run_queue so a launch error
                # is returned to the individual request instead of killing the
                # manager thread and producing a generic timeout/500.
                self._run_queue()
        except Exception as exc:
            self._fatal_error = exc
            self._pw = None
            self._browser = None
            self._context = None

    def _start_browser(self) -> None:
        settings = load_settings()
        executable = _browser_path(settings)

        browser = self._pw.chromium.launch(
            executable_path=executable,
            headless=False,
            args=[
                "--ozone-platform=wayland",
                "--no-first-run",
                "--disable-session-crashed-bubble",
            ],
        )
        self._browser = browser
        self._context = browser.new_context()

        # Auto-allow media permissions for Zoom so Chromium does not show
        # camera/microphone permission prompts during the automated join flow.
        for origin in (
            "https://app.zoom.us",
            "https://zoom.us",
            "https://lausd.zoom.us",
        ):
            try:
                self._context.grant_permissions(
                    ["camera", "microphone"],
                    origin=origin,
                )
            except Exception:
                pass

    def _context_is_alive(self) -> bool:
        if self._context is None:
            return False
        try:
            _ = self._context.pages
            return True
        except Exception:
            self._context = None
            self._tabs.clear()
            return False

    def _run_queue(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                self._cleanup_tabs()
                if not self._context_is_alive():
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

    def _first_visible(self, locators):
        for locator in locators:
            try:
                count = locator.count()
                for index in range(min(count, 5)):
                    item = locator.nth(index)
                    if item.is_visible():
                        return item
            except Exception:
                continue
        return None

    def _fill_zoom_name(self, page, name: str = "Erik") -> bool:
        fields = [
            page.locator('input[placeholder*="name" i]'),
            page.locator('input[aria-label*="name" i]'),
            page.locator('input[name*="name" i]'),
            page.locator('input[id*="name" i]'),
            page.locator('input[type="text"]'),
        ]

        # Zoom can take a few seconds to render the guest pre-join form.
        # Poll briefly instead of attempting the field only once.
        for _ in range(12):
            field = self._first_visible(fields)
            if field is not None:
                try:
                    current = str(field.input_value()).strip()
                except Exception:
                    current = ""

                if not current:
                    field.fill(name)

                try:
                    return str(field.input_value()).strip() == name or bool(current)
                except Exception:
                    return True

            try:
                page.wait_for_timeout(500)
            except Exception:
                break

        return False

    def _zoom_button_text(self, button) -> str:
        values = []
        for attr in ("aria-label", "title", "data-testid", "data-state"):
            try:
                values.append(button.get_attribute(attr) or "")
            except Exception:
                pass
        try:
            values.append(button.inner_text() or "")
        except Exception:
            pass
        try:
            values.append(button.text_content() or "")
        except Exception:
            pass
        return " | ".join(" ".join(v.lower().split()) for v in values if v)

    def _zoom_media_off_labels(self, media: str) -> tuple[str, ...]:
        if media == "video":
            return (
                "включить видео",
                "включить мое видео",
                "включить подачу",
                "включить показ",
                "включить передачу",
                "включить виде",
                "turn on my video",
                "turn on video",
                "start video",
                "start my video",
                "video off",
                "camera off",
            )
        return (
            "включить звук",
            "включить микрофон",
            "включить аудио",
            "unmute my microphone",
            "unmute microphone",
            "unmute my audio",
            "unmute audio",
            "microphone off",
            "audio off",
        )

    def _zoom_media_on_labels(self, media: str) -> tuple[str, ...]:
        if media == "video":
            return (
                "выключить видео",
                "выключить видео для всех",
                "выключить подачу",
                "выключить показ",
                "выключить передачу",
                "turn off my video",
                "turn off video",
                "stop video",
                "stop my video",
                "video on",
            )
        return (
            "выключить звук",
            "выключить микрофон",
            "выключить аудио",
            "mute my microphone",
            "mute microphone",
            "mute my audio",
            "mute audio",
            "microphone on",
            "audio on",
        )

    def _zoom_media_is_off(self, page, media: str) -> bool:
        off_labels = self._zoom_media_off_labels(media)
        buttons = page.locator("button, [role='button']")
        try:
            count = buttons.count()
        except Exception:
            return False

        for index in range(min(count, 150)):
            try:
                button = buttons.nth(index)
                if not button.is_visible():
                    continue

                combined = self._zoom_button_text(button)
                if not combined:
                    continue

                if any(label in combined for label in off_labels):
                    return True

                pressed = (button.get_attribute("aria-pressed") or "").lower()
                checked = (button.get_attribute("aria-checked") or "").lower()
                state = (button.get_attribute("data-state") or "").lower()

                if pressed == "false" or checked == "false":
                    # Only accept this state if the button also describes the
                    # requested media rather than an unrelated toggle.
                    media_word = (
                        ("video", "camera")
                        if media == "video"
                        else ("microphone", "mic", "audio", "sound", "звук", "микроф")
                    )
                    if any(word in combined for word in media_word):
                        return True

                if state in {"off", "inactive", "closed"}:
                    media_word = (
                        ("video", "camera")
                        if media == "video"
                        else ("microphone", "mic", "audio", "sound", "звук", "микроф")
                    )
                    if any(word in combined for word in media_word):
                        return True
            except Exception:
                continue

        # Fallback for compact Russian Zoom pre-join controls where
        # the camera label is truncated visually to something like
        # "Включить по..." and the accessible text has no literal "видео".
        try:
            candidates = []
            for index in range(min(count, 150)):
                button = buttons.nth(index)
                if not button.is_visible():
                    continue
                text = self._zoom_button_text(button)
                normalized = " ".join(text.lower().split())
                if not normalized:
                    continue
                if not (
                    "включить" in normalized
                    or "выключить" in normalized
                    or "mute" in normalized
                    or "unmute" in normalized
                ):
                    continue
                box = button.bounding_box()
                if not box:
                    continue
                candidates.append((box["y"], box["x"], button, normalized))

            if media == "video" and len(candidates) >= 2:
                candidates.sort(key=lambda item: (item[0], item[1]))
                first_y = candidates[0][0]
                row = [
                    item for item in candidates
                    if abs(item[0] - first_y) < 60
                ]
                row.sort(key=lambda item: item[1])

                if len(row) >= 2:
                    video_button = row[1][2]
                    video_text = row[1][3]
                    # In this compact pre-join row: audio is first, video is
                    # second. "Включить..." means the video is already OFF.
                    if "включить" in video_text:
                        return True

                    # If it's still in the ON state, report that it is not OFF
                    # so the caller can click the second media button.
                    if "выключить" in video_text:
                        return False
        except Exception:
            pass

        return False

    def _zoom_media_controls_debug(self, page) -> list[str]:
        controls: list[str] = []
        buttons = page.locator("button, [role='button']")
        try:
            count = buttons.count()
        except Exception:
            return controls

        for index in range(min(count, 150)):
            try:
                button = buttons.nth(index)
                if not button.is_visible():
                    continue
                text = self._zoom_button_text(button)
                lowered = text.lower()
                if any(word in lowered for word in (
                    "video", "camera", "microphone", "mic", "audio",
                    "звук", "микроф", "видео", "камер",
                )):
                    controls.append(text[:180])
            except Exception:
                continue
        return controls[:20]

    def _click_zoom_prejoin_option(self, page, media: str) -> bool:
        on_labels = self._zoom_media_on_labels(media)
        off_labels = self._zoom_media_off_labels(media)

        # Already disabled: do not click, because that would enable it again.
        if self._zoom_media_is_off(page, media):
            return True

        buttons = page.locator("button, [role='button']")
        try:
            count = buttons.count()
        except Exception:
            count = 0

        for index in range(min(count, 150)):
            try:
                button = buttons.nth(index)
                if not button.is_visible():
                    continue

                combined = self._zoom_button_text(button)
                if not combined:
                    continue

                # Never click a button whose label means the media is already off.
                if any(label in combined for label in off_labels):
                    return True

                pressed = (button.get_attribute("aria-pressed") or "").lower()
                checked = (button.get_attribute("aria-checked") or "").lower()
                state = (button.get_attribute("data-state") or "").lower()

                active = any(label in combined for label in on_labels)
                if pressed == "true" or checked == "true" or state in {"on", "active", "open"}:
                    media_words = (
                        ("video", "camera")
                        if media == "video"
                        else ("microphone", "mic", "audio", "sound", "звук", "микроф")
                    )
                    active = active or any(word in combined for word in media_words)

                if not active:
                    continue

                button.click(force=True, timeout=2500)
                page.wait_for_timeout(400)
                return self._zoom_media_is_off(page, media)
            except Exception:
                continue

        # Nested label/span fallback.
        for pattern in on_labels:
            try:
                node = page.get_by_text(
                    re.compile(re.escape(pattern), re.I)
                )
                count = node.count()
                for index in range(min(count, 10)):
                    item = node.nth(index)
                    if not item.is_visible():
                        continue

                    button = item.locator("xpath=ancestor::button[1]")
                    if not button.count():
                        button = item.locator("xpath=ancestor::*[@role='button'][1]")
                    if not button.count():
                        continue

                    target = button.first
                    if target.is_visible():
                        target.click(force=True, timeout=2500)
                        page.wait_for_timeout(400)
                        return self._zoom_media_is_off(page, media)
            except Exception:
                continue

        # Positional fallback for the exact compact pre-join row in
        # the preview: microphone first, camera second.
        if media == "video":
            try:
                candidates = []
                for index in range(min(buttons.count(), 150)):
                    button = buttons.nth(index)
                    if not button.is_visible():
                        continue
                    text = self._zoom_button_text(button)
                    normalized = " ".join(text.lower().split())
                    if not normalized:
                        continue
                    if not (
                        "включить" in normalized
                        or "выключить" in normalized
                        or "mute" in normalized
                        or "unmute" in normalized
                    ):
                        continue
                    box = button.bounding_box()
                    if not box:
                        continue
                    candidates.append((box["y"], box["x"], button, normalized))

                if len(candidates) >= 2:
                    candidates.sort(key=lambda item: (item[0], item[1]))
                    row_y = candidates[0][0]
                    row = [
                        item for item in candidates
                        if abs(item[0] - row_y) < 60
                    ]
                    row.sort(key=lambda item: item[1])

                    if len(row) >= 2:
                        video_button = row[1][2]
                        video_text = row[1][3]
                        if "выключить" in video_text:
                            video_button.click(force=True, timeout=2500)
                            page.wait_for_timeout(400)
                            return self._zoom_media_is_off(page, media)
                        if "включить" in video_text:
                            return True
            except Exception:
                pass

        return self._zoom_media_is_off(page, media)

    def _turn_zoom_toggle_off(
        self,
        page,
        keywords: tuple[str, ...],
        off_phrases: tuple[str, ...],
    ) -> bool:
        joined = " ".join(keywords).lower()
        media = "video" if any(
            word in joined for word in ("camera", "video")
        ) else "audio"
        return self._click_zoom_prejoin_option(page, media)

    def _grant_zoom_media_permissions(self, page) -> None:
        try:
            from urllib.parse import urlparse

            origin_data = urlparse(page.url)
            if origin_data.scheme and origin_data.netloc:
                self._context.grant_permissions(
                    ["camera", "microphone"],
                    origin=f"{origin_data.scheme}://{origin_data.netloc}",
                )
        except Exception:
            pass

    def _prepare_zoom_join(self, page) -> dict:
        # Zoom may first expose the external-app prompt. Cancel it and select
        # the browser path explicitly.
        cancel = self._first_visible([
            page.get_by_role(
                "button",
                name=re.compile(r"^cancel$", re.I),
            ),
            page.get_by_text(
                re.compile(r"^cancel$", re.I),
            ),
        ])
        if cancel is not None:
            try:
                cancel.click()
                page.wait_for_timeout(700)
            except Exception:
                pass

        browser_join = self._first_visible([
            page.get_by_text(
                re.compile(r"join from your browser|join from browser", re.I)
            ),
            page.get_by_role(
                "link",
                name=re.compile(r"join from your browser|join from browser", re.I),
            ),
            page.get_by_role(
                "button",
                name=re.compile(r"join from your browser|join from browser", re.I),
            ),
        ])
        if browser_join is not None:
            try:
                browser_join.click()
            except Exception:
                pass

        # Zoom can redirect to another web origin after the browser-join click.
        self._grant_zoom_media_permissions(page)

        # Give the Web App time to render the actual guest pre-join screen.
        page.wait_for_timeout(2500)

        # Guest/pre-join name. Zoom documents that the browser flow asks for
        # a display name before joining.
        self._fill_zoom_name(page, "Erik")

        # Keep camera and microphone off before the Join action. Zoom's web
        # UI has used both toggle buttons and checkbox/label controls.
        # Zoom's pre-join controls can appear a little after the name
        # field. Retry for a few seconds so we don't miss them.
        video_off = False
        audio_off = False
        for _ in range(8):
            video_off = self._turn_zoom_toggle_off(
                page,
                ("camera", "video"),
                (),
            ) or video_off
            audio_off = self._turn_zoom_toggle_off(
                page,
                ("microphone", "mic", "audio"),
                (),
            ) or audio_off
            if video_off and audio_off:
                break
            page.wait_for_timeout(500)

        if not video_off or not audio_off:
            controls = self._zoom_media_controls_debug(page)
            raise RuntimeError(
                "Zoom pre-join media could not be confirmed OFF. "
                f"video_off={video_off}, audio_off={audio_off}, "
                f"controls={controls}"
            )

        return {
            "ready": bool(video_off and audio_off),
            "video_off": bool(video_off),
            "audio_off": bool(audio_off),
        }

    def open_zoom(self, slot: str = "zoom") -> dict:
        settings = load_settings()
        invite_url = str(settings.get("zoom_url", "")).strip()
        if not invite_url:
            raise RuntimeError("Zoom URL is not configured")

        meeting = re.search(r"/j/(\d+)", invite_url)
        if not meeting:
            raise RuntimeError(
                "Zoom URL must contain a meeting ID like /j/1234567890"
            )

        meeting_id = meeting.group(1)

        # IMPORTANT: never navigate to the invite URL here. Zoom invite pages
        # intentionally try to launch the desktop client via zoommtg://, which
        # invokes xdg-open on Linux. Going directly to the Web App avoids that
        # external-protocol handoff entirely.
        web_url = f"https://app.zoom.us/wc/join/{meeting_id}"

        def job() -> dict:
            page = self._new_page(slot)

            if page.url != web_url:
                page.goto(
                    web_url,
                    wait_until="domcontentloaded",
                    timeout=30000,
                )

            page.bring_to_front()
            self._grant_zoom_media_permissions(page)

            # Let the Web App render its browser-join/pre-join UI, then run
            # the name + camera + microphone preparation in the same manager
            # thread.
            page.wait_for_timeout(2500)
            join_state = self._prepare_zoom_join(page)
            page.wait_for_timeout(500)
            page.bring_to_front()

            if not join_state["ready"]:
                raise RuntimeError(
                    "Zoom pre-join is not ready: "
                    f"video_off={join_state['video_off']}, "
                    f"audio_off={join_state['audio_off']}"
                )

            return {
                "success": True,
                "action": "open_zoom",
                "slot": slot,
                "meeting_id": meeting_id,
                "ready_to_join": True,
                "video_off": True,
                "audio_off": True,
                "url": page.url,
            }

        return self.call(job)

    def join_zoom(self, slot: str = "zoom") -> dict:
        def job() -> dict:
            page = self._tabs.get(slot)
            if page is None or page.is_closed():
                raise RuntimeError("Zoom pre-join tab is not open")

            join = self._first_visible([
                page.get_by_role(
                    "button",
                    name=re.compile(
                        r"^(join|войти|присоединиться)$",
                        re.I,
                    ),
                ),
                page.get_by_text(
                    re.compile(
                        r"^(join|войти|присоединиться)$",
                        re.I,
                    ),
                ),
            ])

            if join is None:
                raise RuntimeError("Zoom Join/Войти button was not found")

            page.bring_to_front()
            join.click(force=True, timeout=5000)
            page.wait_for_timeout(1200)

            return {
                "success": True,
                "action": "join_zoom",
                "slot": slot,
                "url": page.url,
                "joined": True,
            }

        return self.call(job)

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

            # Reuse an already-authenticated LAUSD tab instead of restarting
            # the Microsoft login flow on every Telegram/Admin click.
            current = (page.url or "").lower()
            if (
                current
                and current != "about:blank"
                and "login.microsoftonline.com" not in current
                and "login.live.com" not in current
                and "student/login" not in current
                and "login" not in current
            ):
                page.bring_to_front()
                return {
                    "success": True,
                    "action": "schoology_login",
                    "slot": slot,
                    "already_logged_in": True,
                    "url": page.url,
                }

            page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

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

            # Microsoft can land directly on the password step when a prior
            # account choice is remembered. Handle that before looking for the
            # account tile/email field.
            password_field = page.locator('input[type="password"]')
            try:
                has_password = password_field.count() and password_field.first.is_visible()
            except Exception:
                has_password = False

            if not has_password:
                _click_account_tile(page, user)
                page.wait_for_timeout(1200)

            _fill_password(page, password)

            # Microsoft may show the optional "Stay signed in?" step.
            page.wait_for_timeout(1200)
            stay_yes = self._first_visible([
                page.get_by_role("button", name=re.compile(r"^yes$", re.I)),
                page.get_by_text(re.compile(r"^yes$", re.I)),
            ])
            if stay_yes is not None:
                try:
                    stay_yes.click()
                except Exception:
                    pass

            page.wait_for_timeout(6000)
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
            from .input_actions import send_key

            page = self._new_page(slot)
            page.bring_to_front()
            result = send_key(combo)
            result["slot"] = slot
            return result

        return self.call(job)

    def type_text(self, slot: str, value: str) -> dict:
        def job() -> dict:
            from .input_actions import type_text

            page = self._new_page(slot)
            page.bring_to_front()
            result = type_text(value)
            result["slot"] = slot
            return result

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
        if not self._started:
            return {"success": True, "action": "close", "slot": slot, "open": False}

        def job() -> dict:
            page = self._tabs.get(slot)
            if page is not None and not page.is_closed():
                page.close()
            self._tabs.pop(slot, None)
            return {"success": True, "action": "close", "slot": slot}

        return self.call(job)

    def focus_slot(self, slot: str) -> dict:
        if not self._started:
            raise RuntimeError(f"Browser tab '{slot}' is not open")

        def job() -> dict:
            found = self._focus_slot(slot)
            if not found:
                raise RuntimeError(f"Browser tab '{slot}' is not open")
            return {"success": True, "action": "focus", "slot": slot}

        return self.call(job)

    def tabs(self) -> list[dict[str, Any]]:
        if not self._started:
            return []

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
        if not self._started:
            return {"open": False, "messages": [], "new_messages": []}

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
