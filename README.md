# Okiner

Okiner is a Python Discord bot for roleplay, family relationships, community engagement, and server moderation. Data is stored in a local SQLite database (`rp.db`).

Features:

- Configurable roleplay pools with case-specific text (standard, selfcase, nullcase), image rotation, member autocomplete, and temporary "RP back" buttons.
- Marriage proposals, divorce, adoption, disowning, and a family tree image.
- Native alt/trust analysis (`/scan`), server configuration, and a honeypot channel that bans non-staff who post in it.
- Message activity tracking and custom emoji / reaction leaderboards.

## Privacy

See [PRIVACY.md](PRIVACY.md) for what data Okiner collects, stores, and uses. Security design notes are in [SECURITY_SNAPSHOT.md](SECURITY_SNAPSHOT.md).

## Discord Application Configuration

OAuth scopes: `bot`, `applications.commands`.

Requested bot permissions:

- Attach Files
- Ban Members (honeypot)
- Embed Links
- Manage Messages (honeypot cleanup when a ban is not possible)
- Read Message History (used by `oki!sync` replies)
- Send Messages
- Send Messages in Threads
- Use External Emojis
- Use Application Commands (slash commands)
- View Channels

Changing the requested permissions only affects **new** invite links. Servers that already have the bot must grant any newly added permission (for example Ban Members or Read Message History) manually.

Gateway intents to enable in the Developer Portal:

- Server Members Intent (member lookup, autocomplete, join dates)
- Message Content Intent (emoji tracking and the `oki!sync` prefix command)

The Presence Intent is **not** used. Turn it off in the Developer Portal.

`DISCORD_APPLICATION_ID` can be added to `.env` so the bot logs a ready-to-use invite URL at startup.

## Requirements

- Python 3.11 or newer (developed and tested on 3.13).
- discord.py 2.6 or newer (uses `LayoutView` / `Container`); `requirements.txt` pins exact versions.
- A system font for the family tree image. On Debian/Ubuntu: `sudo apt install -y fonts-dejavu-core`. Without it the tree falls back to Pillow's built-in font.

## Setup

### Windows (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

### Debian / Debian-based Linux

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip fonts-dejavu-core
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Add your bot token (`DISCORD_TOKEN`) and application ID to `.env`.

## Data Storage

Okiner uses `rp.db` in the project directory (SQLite, WAL mode, so `rp.db-wal` and `rp.db-shm` files appear while it runs).

- On startup, versioned migrations run (tracked with `PRAGMA user_version`). Before any pending migration, a consistent backup named `rp.db.bak-<UTC timestamp>` is written next to the database. Keep it until the new version has run cleanly.
- A database from a newer version of the code is refused at startup ("database is newer than this code"). Restore the backup to roll back.
- When backing up manually while the bot runs, do not copy `rp.db` alone; use SQLite's `.backup` or copy the `-wal` file too.

The database stores:

- RP types per server, with image URLs, text templates, and action text templates (with the Discord user ID of the adder).
- Marriages and adoptions. These are **global** (not tied to a server).
- Per-server configuration: log channel, honeypot channel, verified role, moderator role, inactivity toggle.
- Allowlisted channels for `/scan`.
- Member activity counters (message count, join and last-active timestamps, inactivity fields).
- Custom emoji message and reaction counts per server.

Activity counters are held in memory and written every 15 seconds and at shutdown.

## Run

```bash
python3 main.py        # Windows: python main.py
```

After the bot starts, the owner runs `oki!sync` in a server to register slash commands for that server (fast, for testing) or `oki!sync global` to register them everywhere (can take up to an hour to propagate).

## Commands

All slash commands work only inside servers. Management and security commands require the listed permission. Permissions are checked when the command runs and again when buttons or forms are used.

### Roleplay and Family

| Command | Permission | Description |
|---|---|---|
| `/rp <type> [target]` | Everyone | Perform an RP interaction. |
| `/add_rp <type> [image_url] [image_file]` | Manage Messages | Create an RP type with an image (URL or upload) and chosen case modes. Uploaded images use Discord CDN links that can expire; prefer `image_url`. |
| `/edit_rp <type>` | Manage Messages | Add images, texts, or action texts to an existing type. |
| `/manage_rp` | Manage Messages | Browse, edit, and delete types and entries. Image entries are previewed. |
| `/marry <user>` | Everyone | Propose marriage (30 second cooldown, one pending proposal per pair). |
| `/adopt <user>` | Everyone | Ask to adopt someone (same limits). |
| `/divorce <user>` | Everyone | End a marriage. |
| `/disown <user>` | Everyone | End a parent-child record. |
| `/familytree [user]` | Everyone | Image of a member's family. Shows only people who are in this server and at most the 40 closest relatives. |

### Moderation and Security (Crouton)

| Command | Permission | Description |
|---|---|---|
| `/crouton setup` | Administrator | Set log channel, verified role, moderator role. Provided options replace the saved value; omitted options are kept (use /crouton clear to clear). |
| `/crouton clear` | Administrator | Clear the log channel, verified role, moderator role, and honeypot channel. Does not change scan channels or the inactivity setting. Reports if there are no saved settings to clear. |
| `/crouton help` | Everyone | Command reference. |
| `/crouton uptime` | Everyone | Process uptime. |
| `/scan <member>` | Manage Messages | Alt/trust analysis card, only in allowlisted channels, the log channel, or for admins and the moderator role. |
| `/sethoneypot [channel]` | Administrator | Set or clear the honeypot channel (omitting the channel clears it). Cannot be the log channel. |
| `/addscanchannel`, `/removescanchannel` | Manage Messages | Manage the `/scan` allowlist. |
| `/enableunverification`, `/disableunverification` | Manage Messages | **Planned.** The setting is stored, but the automatic unverification sweep is not implemented yet, so nothing is unverified automatically. |
| `/manualresetinactivity <member>` | Manage Messages | Reset a member's inactivity timer. |

### Leaderboards

| Command | Description |
|---|---|
| `/emojirank [top/bottom]` | Top 10 custom emoji by message use. |
| `/reactionrank [top/bottom]` | Top 10 custom emoji by reaction use. |

## Honeypot

Anyone posting in the honeypot channel (or a thread under it) is banned, and their last hour of messages is removed. Exempt: the server owner, anyone with Administrator, Manage Server, Ban Members, Kick Members, or Manage Messages, and members with the configured moderator role. The bot needs Ban Members and a role above the target. If a ban is not possible, it deletes the message instead and reports why in the log channel. Test with an account that is not exempt, and never set a honeypot in a channel members use normally.

## Tests

```bash
.venv/bin/python3 -m unittest discover
.venv/bin/python3 -m pyflakes *.py cogs/*.py tests/*.py
```
