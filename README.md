# Okiner

Okiner is a Python-based Discord bot for server member interaction, community engagement, roleplay, security, and moderation features.

Current features include configurable roleplay command pools, case-specific roleplay text, image rotation, member autocomplete, temporary RP back buttons, marriage proposals, divorce, adoption requests, disowning adopted children, native account alt detection (`/scan`), server configuration, honeypot protection, inactivity tracking, and custom emoji/reaction leaderboards. Persistent data is stored in a local SQLite database (`rp.db`).

## Privacy

See [PRIVACY.md](PRIVACY.md) for what data Okiner collects, stores, and uses.

## Discord Application Configuration

The bot is intended to use the following OAuth scopes:

- `bot`
- `applications.commands`

The requested bot permissions are:

- Add Reactions
- Attach Files
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

## Data Storage

Okiner creates and uses `rp.db` in the project directory. On startup, it creates missing tables and applies lightweight migrations for older roleplay, adoption, marriage, guild configuration, scan channels, member behavior, and emoji tables.

The database stores:

- RP types configured per server.
- Saved RP image URLs, embed text templates, and action text templates.
- Discord user IDs associated with saved RP entries.
- Marriage records.
- Adoption records.
- Per-guild configuration (log channels, honeypot channels, verified roles, moderator roles, inactivity system toggles).
- Allowlisted channels for `/scan`.
- Member behavior telemetry (message counts, last active timestamps, inactivity status).
- Guild custom emoji usage stats.

## Run

### Windows (PowerShell)

```powershell
python main.py
```

### Debian / Debian-based Linux

```bash
python3 main.py
```

After the bot starts, run `oki!sync` (owner only) in a server to register slash commands. Use `oki!sync global` to push them globally, or just `oki!sync` to push to the current server only (faster for testing).

## Commands

All slash commands only work inside servers. Management and security commands require appropriate permissions (Manage Messages or Administrator).

### Roleplay & Family

| Command | Description |
|---|---|
| `/rp <type> [target]` | Perform an RP interaction using saved pools. |
| `/add_rp <type> [image_url] [image_file]` | Create a new RP type with dual image input (URL or file upload) and 4 case modes. |
| `/edit_rp <type>` | Append additional entries or image URLs to an existing RP type. |
| `/manage_rp` | Interactive management, browsing, and deletion of RP types and entries. |
| Family commands | Marriage, divorce, adoption, disown, family tree generation. |

### Moderation & Security (Crouton Suite)

| Command | Permission | Description |
|---|---|---|
| `/crouton setup` | Administrator | Configure log channel, verified role, and moderator role. |
| `/crouton help` | Everyone | Display command reference and help guide. |
| `/crouton uptime` | Everyone | Report bot process uptime. |
| `/scan <user>` | Manage Messages | Run native Python alt/trust analysis and post scan card. |
| `/sethoneypot <channel>` | Administrator | Set or clear the server honeypot channel. |
| `/addscanchannel <channel>` | Manage Messages | Allowlist a channel for `/scan`. |
| `/removescanchannel <channel>` | Manage Messages | Remove a channel from the `/scan` allowlist. |
| `/enableunverification` | Manage Messages | Enable automatic unverification sweep. |
| `/disableunverification` | Manage Messages | Disable automatic unverification sweep. |
| `/manualresetinactivity <user>` | Manage Messages | Reset a member's inactivity timer. |

### Leaderboards

| Command | Description |
|---|---|
| `/emojirank <top/bottom>` | Paginated custom emoji message usage leaderboard. |
| `/reactionrank <top/bottom>` | Paginated custom emoji reaction usage leaderboard. |
