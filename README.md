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
