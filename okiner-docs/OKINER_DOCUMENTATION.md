# Okiner Bot Documentation & Administrator Guide

Last updated: November 7, 2026

## 1. System Overview

Okiner is a modular Discord bot written in Python with `discord.py` and asynchronous SQLite (`asqlite`). It provides:

1. **Roleplay**: configurable interaction pools with Standard, Selfcase, and Nullcase text, placeholders, image rotation (URL or upload), and interactive management.
2. **Family**: marriage proposals, divorce, adoption, disowning, and a family tree image.
3. **Crouton moderation and security**: native alt/trust scoring (`/scan`), server setup, a honeypot channel with automatic bans, and a scan-channel allowlist. The automatic unverification sweep is **planned and not implemented**.
4. **Engagement**: message activity counters and custom emoji / reaction leaderboards.

---

## 2. Prerequisites & Setup

- **Python** 3.11 or newer (developed on 3.13).
- **discord.py** 2.6 or newer. `requirements.txt` pins exact versions.
- **SQLite** (bundled with Python).
- **Fonts** (Linux): `sudo apt install -y fonts-dejavu-core` so family trees render with a proper font.

### Installation

Debian / Linux:
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git fonts-dejavu-core
git clone <repository-url> OkinerExperimental
cd OkinerExperimental
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Windows (PowerShell):
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

### Environment (`.env`)
```env
DISCORD_TOKEN=your_bot_token_here
DISCORD_APPLICATION_ID=your_application_id_here
```

### Discord Developer Portal

1. **Privileged intents**: enable **Server Members** and **Message Content**. Leave **Presence** off.
2. **OAuth2 scopes**: `bot`, `applications.commands`.
3. **Bot permissions**: Attach Files, Ban Members, Embed Links, Manage Messages, Read Message History, Send Messages, Send Messages in Threads, Use External Emojis, Use Application Commands, View Channels.

Permission changes affect only new invites. Existing servers must grant newly added permissions (Ban Members, Read Message History) by hand. The startup log prints an invite URL with the current permission set.

---

## 3. Running & Command Sync

```bash
python3 main.py
```

On startup Okiner applies database migrations (with an automatic backup first), then loads its cogs. Owner-only prefix commands register slash commands:

- `oki!sync`: sync to the current server (fast, for testing).
- `oki!sync global`: sync everywhere (up to an hour to propagate).

The bot needs permission to send messages and read history in the channel where you run them.

---

## 4. Slash Command Reference

All commands work only in servers.

### Roleplay and Family

| Command | Permission | Description |
|---|---|---|
| `/rp <type> [target]` | Everyone | Run an RP interaction. Picks the standard, selfcase, or nullcase pool, fills placeholders, and may attach an "RP back" button for the target. |
| `/add_rp <type> [image_url] [image_file]` | Manage Messages | Guided creation of a type. Exactly one of image URL or upload is required. Uploaded images use Discord CDN links that can expire, so a hosted URL is more durable. |
| `/edit_rp <type>` | Manage Messages | Add an image, text, or action text to an existing type. Duplicates are rejected. |
| `/manage_rp` | Manage Messages | Browse, edit, and delete entries or whole types. With more than 25 types the type list is paged. Image entries are shown as previews. |
| `/marry <user>` | Everyone | Propose marriage. 30 second cooldown; one pending proposal per pair. |
| `/adopt <user>` | Everyone | Ask to adopt a member. Same limits. |
| `/divorce <user>` | Everyone | End your marriage with that user. |
| `/disown <user>` | Everyone | End a parent-child record where you are the parent. |
| `/familytree [user]` | Everyone | Family tree image. Only people in this server appear, and at most the 40 closest relatives. |

Relationships are global: a marriage or adoption is not limited to one server.

### Crouton

| Command | Permission | Description |
|---|---|---|
| `/crouton setup` | Administrator | Set log channel, verified role, moderator role. Omitted options keep their stored values. Rejected: @everyone as a role, a managed role as the verified role, a log channel the bot cannot post in, and a log channel equal to the honeypot channel. |
| `/crouton help` / `uptime` | Everyone | Help text and uptime. |
| `/scan <member>` | Manage Messages | Trust analysis card (account age, avatar, other public profile signals). Allowed in allowlisted channels, the log channel, or for administrators and the moderator role. |
| `/sethoneypot [channel]` | Administrator | Set or clear the honeypot channel. Warns if the bot lacks Ban Members. |
| `/addscanchannel`, `/removescanchannel` | Manage Messages | Maintain the allowlist. |
| `/enableunverification`, `/disableunverification` | Manage Messages | Stores a setting only. The sweep is not implemented, so nothing is unverified. |
| `/manualresetinactivity <member>` | Manage Messages | Reset a member's inactivity timer. |

### Engagement

| Command | Permission | Description |
|---|---|---|
| `/emojirank [top/bottom]` | Everyone | Top 10 custom emoji by message use. |
| `/reactionrank [top/bottom]` | Everyone | Top 10 custom emoji by reaction use. |

---

## 5. Administrator Workflows & Safety

1. **Initial setup**: run `/crouton setup`, then `/sethoneypot` only if you want one.
2. **Honeypot**: any non-exempt member who posts in the honeypot channel (or a thread in it) is banned and their last hour of messages removed. Exempt: owner, Administrator, Manage Server, Ban Members, Kick Members, Manage Messages, and the moderator role. Put the bot's role above ordinary members. If banning is impossible, the message is deleted and the log channel says why. Never place a honeypot in a channel people use normally.
3. **Roleplay content**: use `/add_rp`, `/edit_rp`, and `/manage_rp`. Display names inserted into text are escaped so they cannot create links or pings.
4. **Permissions at click time**: management menus and forms re-check Manage Messages when used, so removing a moderator's permission takes effect immediately.
5. **Backups**: a backup is written automatically before database upgrades. To back up a running bot, use SQLite's backup (`sqlite3 rp.db ".backup file"`), not a plain file copy, because the database is in WAL mode.
6. **Privacy**: see [PRIVACY.md](../PRIVACY.md).
