# Okiner

Okiner is a Python-based Discord bot project intended for server member interaction, community engagement, and roleplay-focused features.

The repository is currently set up with the core structure needed to start development, including dependency management, environment configuration, and a minimal bot entrypoint.

## Discord Application Configuration

The bot is intended to use the following OAuth scopes:

- `bot`
- `applications.commands`

The requested bot permissions are:

- Add Reactions
- Attach Files
- Bypass Slowmode
- Change Nickname
- Embed Links
- Send Messages
- Send Messages in Threads
- Use External Emojis
- Use External Stickers
- Use Slash Commands
- View Audit Log
- View Channels

`DISCORD_APPLICATION_ID` can be added to `.env` so the bot can log a ready-to-use invite URL at startup.

Note: Discord does not expose "Bypass Slowmode" as a standalone OAuth permission value in the same way as the other permissions listed above. The project documents it here because it is part of the intended bot capability set, but the generated invite URL only includes the explicit permission flags available through the Discord API.

The bot also expects the following gateway intents to be enabled in the Discord Developer Portal and in code:

- Presence Intent
- Server Members Intent
- Message Content Intent

## Setup

### Windows (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Add your bot token and application ID to `.env`.

### Debian / Debian-based Linux

Install Python, virtual environment support, and `pip`:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

Create and activate a virtual environment, then install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Add your bot token and application ID to `.env`.

## Run

### Windows (PowerShell)

```powershell
python main.py
```

### Debian / Debian-based Linux

```bash
python3 main.py
```

The current starter command is a slash command:

- `/ping`
