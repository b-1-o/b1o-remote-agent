import subprocess
from .config import ZOOM_URL

def _spawn(command: list[str]) -> None:
    subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

def get_status() -> dict:
    hostname = subprocess.check_output(["hostname"], text=True).strip()
    return {"online": True, "hostname": hostname}

def open_zoom() -> dict:
    _spawn(["xdg-open", ZOOM_URL])
    return {"success": True, "action": "open_zoom"}

def lock_pc() -> dict:
    _spawn(["loginctl", "lock-session"])
    return {"success": True, "action": "lock"}

def shutdown_pc() -> dict:
    _spawn(["systemctl", "poweroff"])
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
        "note": "Targets only an existing user session; the OS login password is not transmitted.",
    }
