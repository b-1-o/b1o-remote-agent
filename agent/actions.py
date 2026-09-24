import subprocess

from .browser_manager import browser_manager


def get_status() -> dict:
    hostname = subprocess.check_output(["hostname"], text=True).strip()
    return {"online": True, "hostname": hostname}


def open_url(url: str, slot: str = "url") -> dict:
    if not (url.startswith("https://") or url.startswith("http://")):
        raise ValueError("Only http/https URLs are allowed")
    return browser_manager().open_url(slot, url)


def open_zoom(slot: str = "zoom") -> dict:
    return browser_manager().open_zoom(slot)


def start_zoom_async(slot: str = "zoom") -> dict:
    return browser_manager().start_zoom_async(slot)


def zoom_state() -> dict:
    return browser_manager().zoom_state()


def join_zoom(slot: str = "zoom") -> dict:
    return browser_manager().join_zoom(slot)


def open_schoology(slot: str = "lausd") -> dict:
    return browser_manager().open_schoology(slot)


def login_schoology(slot: str = "lausd") -> dict:
    return browser_manager().login_schoology(slot)


def start_school_mode() -> dict:
    return browser_manager().start_school_mode()


def browser_tabs() -> list[dict]:
    return browser_manager().tabs()


def browser_focus(slot: str) -> dict:
    return browser_manager().focus_slot(slot)


def browser_close(slot: str) -> dict:
    return browser_manager().close_slot(slot)


def browser_zoom_chat() -> dict:
    return browser_manager().zoom_chat()


def run_command(command: dict) -> dict:
    command_id = str(command.get("id", "")).strip()
    title = str(command.get("title", "")).strip()
    actions = command.get("actions")

    if not command_id or not title or not isinstance(actions, list) or not actions:
        raise ValueError("Invalid command")

    results = []
    slot = {
        "open_zoom": "zoom",
        "open_schoology": "lausd",
    }.get(command_id, command_id)

    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("Invalid action")
        action_type = action.get("type")

        if action_type == "open_url":
            url = str(action.get("url", "")).strip()
            if not (url.startswith("https://") or url.startswith("http://")):
                raise ValueError("open_url requires http/https URL")
            results.append(open_url(url, slot))

        elif action_type == "open_zoom":
            results.append(open_zoom(slot))

        elif action_type == "open_schoology":
            results.append(login_schoology(slot))

        elif action_type == "key":
            combo = action.get("combo")
            if not isinstance(combo, list) or not combo:
                raise ValueError("key requires combo")
            results.append(browser_manager().send_key(slot, combo))

        elif action_type == "type":
            results.append(
                browser_manager().type_text(slot, str(action.get("text", "")))
            )

        else:
            raise ValueError(f"Unsupported action: {action_type}")

    return {
        "success": True,
        "action": "command",
        "command_id": command_id,
        "title": title,
        "results": results,
    }


def lock_pc() -> dict:
    subprocess.Popen(
        ["loginctl", "lock-session"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {"success": True, "action": "lock"}


def shutdown_pc() -> dict:
    subprocess.Popen(
        ["systemctl", "poweroff"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {"success": True, "action": "shutdown"}


def unlock_session() -> dict:
    username = subprocess.check_output(["id", "-un"], text=True).strip()
    sessions = subprocess.check_output(
        ["loginctl", "list-sessions", "--no-legend"],
        text=True,
    ).splitlines()

    unlocked = []

    for line in sessions:
        parts = line.split()
        if len(parts) < 3 or parts[2] != username:
            continue

        session_id = parts[0]
        result = subprocess.run(
            ["loginctl", "unlock-session", session_id],
            capture_output=True,
            text=True,
        )

        if result.returncode == 0:
            unlocked.append(session_id)

    return {
        "success": bool(unlocked),
        "action": "unlock",
        "sessions": unlocked,
    }
