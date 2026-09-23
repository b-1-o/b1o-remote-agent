from agent.actions import open_schoology, open_url, open_zoom
from agent.input_actions import send_key, type_text

def execute_action_sync(action: dict) -> None:
    action_type = action.get("type")
    if action_type == "open_url": open_url(str(action["url"])); return
    if action_type == "open_zoom": open_zoom(); return
    if action_type == "open_schoology": open_schoology(); return
    if action_type == "key": send_key(action["combo"]); return
    if action_type == "type": type_text(str(action.get("text", ""))); return
    raise ValueError(f"Unsupported action: {action_type}")

def execute_command_sync(command: dict) -> None:
    for action in command.get("actions", []): execute_action_sync(action)