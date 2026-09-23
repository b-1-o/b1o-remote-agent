# b1o Remote

Personal remote-control system for a CachyOS desktop.

## Features

- authenticated local FastAPI agent
- PC status
- open a fixed Zoom Web URL
- lock the PC
- shutdown the PC
- Telegram inline-button control
- systemd user services

## Architecture

Phone -> Telegram -> bot -> local agent -> CachyOS

The agent never exposes arbitrary shell execution.

## Setup

1. Create the virtual environment.
2. Install requirements.
3. Copy .env.example to .env.
4. Generate a token with: openssl rand -hex 32
5. Set B1O_REMOTE_TOKEN.
6. Set B1O_ZOOM_URL to your fixed Zoom Web link.
7. Create a Telegram bot with BotFather.
8. Set B1O_TELEGRAM_TOKEN.
9. Set B1O_TELEGRAM_CHAT_ID to your own chat ID.

Run the agent with:
python -m uvicorn agent.main:app --host 127.0.0.1 --port 8765

Run the bot with:
python -m bot.bot

For systemd:
mkdir -p ~/.config/systemd/user
cp systemd/b1o-remote-agent.service ~/.config/systemd/user/
cp systemd/b1o-remote-bot.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now b1o-remote-agent.service
systemctl --user enable --now b1o-remote-bot.service

## Security

Never commit .env.
Never add arbitrary shell execution to the remote API.
The Telegram bot accepts commands only from the configured chat ID.

## Next

Wake-on-LAN needs a controller that remains online while the PC is powered off. The next implementation can add WOL plus an external controller or another always-on device.


## School Mode

Weekdays at 08:20, the user service opens the LAUSD Schoology student login page and fills the configured credentials. At 08:28 it opens the configured Zoom Web meeting.

Configure these only in local .env:
- B1O_SCHOOLOGY_USER
- B1O_SCHOOLOGY_PASSWORD
- B1O_ZOOM_URL
- B1O_BROWSER_EXECUTABLE
- B1O_BROWSER_PROFILE
- B1O_ZOOM_TIME

Never commit .env.

The scheduler uses a persistent browser profile so a normal school session can be reused when possible. If the district presents MFA, CAPTCHA, or another interactive security check, the user must complete it manually.

School Mode does not auto-generate or submit schoolwork. Opening assignment links and typing/submitting answers remains a user-controlled action.


## Telegram control panel

The bot is the main configuration UI.

Open `/start` and use:

- School Mode: enable/disable and run now
- Settings: Schoology URL, email, password, school time, Zoom time, school days, Zoom URL, Brave path, browser profile
- Status, lock and shutdown

Settings are stored locally at `~/.local/share/b1o-remote/settings.json` with owner-only permissions.

The Schoology password is never displayed by the bot. When the password is sent to the bot, the bot attempts to delete that Telegram message immediately after saving it locally.

The bot only accepts messages and buttons from `B1O_TELEGRAM_CHAT_ID`.

For Telegram-configurable scheduling, enable the long-running `b1o-school.service`:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/b1o-school.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now b1o-school.service
```

The old `b1o-school.timer` is not required for the configurable scheduler.


## Telegram controller

The bot keeps one persistent control panel message and removes transient input messages when possible. The main UI has School, Browser, Keyboard, Commands, Settings, Status, Lock and Shutdown.

School Mode has separate `Zoom` and `LAUSD` actions plus a full scheduled run.

### Remote keyboard

The Keyboard panel sends only predefined key combinations and text through the local agent. The implementation uses `ydotool`, which provides virtual keyboard input on Linux; the Arch/CachyOS package includes `ydotool` and a user service. `ydotool` requires access to `/dev/uinput` and the `ydotoold` daemon.

Install on CachyOS:

```bash
sudo pacman -S ydotool
systemctl --user enable --now ydotool.service
```

Do not expose the agent beyond localhost. The bot is restricted to the configured Telegram chat ID.

### Admin command packs

Upload a JSON file from Telegram → Commands → Upload command pack. Only these action types are accepted:

- `open_url`
- `key`
- `type`
- `open_zoom`
- `open_schoology`

Arbitrary shell commands are intentionally rejected. See `examples/commands.json` for the format.

### Unlock

The Unlock button asks for the PC password once. The bot deletes the Telegram message after receiving it and does not write the password to the settings file. The local agent uses the configured input helper to type it and press Enter.


## Architecture

PC Admin (`http://127.0.0.1:8788`) is the only configuration surface. It manages School Mode, links, schedule, PC unlock password, Brave and custom Telegram buttons.

Telegram is runtime-only: School Mode ON/OFF, Zoom, LAUSD, custom buttons, Status, Unlock, Lock and Shutdown. It does not expose settings or command uploads.

The Telegram panel keeps one message and transient user messages are deleted when possible.

Custom buttons are stored locally and can be created/deleted from the Admin panel. Schedules can trigger those commands automatically.

Do not expose the Admin panel outside localhost without adding authentication and transport security.
