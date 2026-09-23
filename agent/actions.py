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
