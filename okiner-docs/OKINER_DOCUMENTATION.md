# Okiner Bot Documentation & Administrator Guide

Last updated: October 17, 2026

## 1. System Overview

**Okiner** is a sophisticated, modular Discord bot engineered in Python using `discord.py` and asynchronous SQLite (`asqlite`) persistence. Designed for high performance, multi-guild safety, and clean separation of concerns, Okiner provides four core operational suites:
1. **Roleplay Suite**: Configurable interaction pools with multi-case support (Standard, Selfcase, Nullcase, and Standard + Self + Null), dynamic placeholder substitution, dual image input support (hosted URL or direct file attachment), and interactive management browsers.
2. **Family & Relationship Suite**: Marriage proposals, divorces, adoption requests, disowns, and interactive family tree rendering.
3. **Crouton Moderation & Security Suite**: Native Python trust and alt scoring (`/scan`), server configuration wizards (`/crouton setup`), secure honeypot trap channels with automatic ban enforcement, channel allowlisting, and inactivity sweeping.
4. **Engagement & Telemetry Suite**: Message activity tracking, custom emoji message/reaction leaderboards, and interaction telemetry.

---

## 2. Prerequisites & Environment Setup

### System Requirements
- **Python**: Version 3.10 or higher.
- **Database**: SQLite3 (bundled with Python standard library).
- **Environment**: Linux (Debian/Ubuntu/CentOS) or Windows (PowerShell).

### Installation Instructions

#### Debian / Linux Environments
```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
git clone <repository-url> OkinerExperimental
cd OkinerExperimental
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

#### Windows (PowerShell)
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

### Environment Configuration (`.env`)
Populate your `.env` file with your Discord credentials:
```env
DISCORD_TOKEN=your_bot_token_here
DISCORD_APPLICATION_ID=your_application_id_here
```

### Discord Developer Portal Configuration
1. **Bot Intents**: Enable the following Privileged Gateway Intents:
   - **Presence Intent**
   - **Server Members Intent**
   - **Message Content Intent**
2. **OAuth2 Scopes**: `bot`, `applications.commands`
3. **Bot Permissions**:
   - Add Reactions, Attach Files, Change Nickname, Embed Links
   - Send Messages, Send Messages in Threads
   - Use External Emojis, Use External Stickers, Use Slash Commands
   - View Audit Log, View Channels

---

## 3. Running & Command Synchronization

### Startup
Launch the bot from the project root:
- **Linux**: `python3 main.py`
- **Windows**: `python main.py`

### Slash Command Registration (`oki!sync`)
Okiner uses owner-restricted prefix commands for deploying slash commands:
- `oki!sync` — Syncs application commands immediately to the current server (recommended for testing and rapid development).
- `oki!sync global` — Registers commands globally across all Discord servers where the bot is installed (note: global propagation can take up to 1 hour per Discord API limits).

---

## 4. Complete Slash Command Reference

### Roleplay & Family Commands (`cogs/rp_commands.py`, `cogs/family_commands.py`)

| Command | Permission | Description |
|---|---|---|
| `/rp <type> [target]` | Everyone | Execute a roleplay interaction. Automatically resolves target metadata, selects appropriate case pool (standard, selfcase, or nullcase), applies placeholder substitutions, and attaches temporary back buttons. |
| `/add_rp <type> [image_url] [image_file]` | Manage Messages (Moderator) | Launch a guided flow to create a new roleplay type. Enforces strict XOR validation for dual image inputs (either a hosted URL or direct file upload), followed by an interactive mode selection view (`Standard Only`, `Standard + Selfcase`, `Standard + Nullcase`, `Standard + Self + Null`) and a submission modal. |
| `/edit_rp <type>` | Manage Messages (Moderator) | Open an interactive options menu to append additional image URLs, embed text templates, or action headers to an existing roleplay type. |
| `/manage_rp` | Manage Messages (Moderator) | Open a multi-step interactive paginated browser to browse, navigate, edit in place, or delete specific entries across all case pools, or remove an entire roleplay type. |
| `/marry <user>` | Everyone | Propose marriage to another server member. Sends an interactive confirmation prompt. |
| `/divorce <user>` | Everyone | Terminate an existing marriage relationship. |
| `/adopt <user>` | Everyone | Request adoption of another server member with confirmation handling. |
| `/disown <user>` | Everyone | Disown an adopted child or parent relationship. |
| `/familytree [user]` | Everyone | Render and display a member's complete family tree (spouse, parents, children). |

### Crouton Moderation & Security Suite (`cogs/moderation.py`)

| Command | Permission | Description |
|---|---|---|
| `/crouton setup` | Administrator | Run the interactive setup wizard to configure server log channels, verified member roles, and moderator roles. |
| `/crouton help` | Everyone | Display the comprehensive Crouton command reference and help guide. |
| `/crouton uptime` | Everyone | Report current bot process uptime and operational status. |
| `/scan <user>` | Manage Messages | Perform automated trust analysis (checking account creation age, default avatars, invite tracking) and post an interactive scan card embed. |
| `/sethoneypot <channel>` | Administrator | Designate or clear a honeypot trap channel. Any non-staff message posted here triggers an immediate automatic ban and audit log entry. |
| `/addscanchannel <channel>` | Manage Messages | Allowlist a specific channel for `/scan` execution. |
| `/removescanchannel <channel>` | Manage Messages | Revoke channel allowlist status for `/scan`. |
| `/enableunverification` | Manage Messages | Enable automatic inactivity tracking sweeps and unverification flows. |
| `/disableunverification` | Manage Messages | Disable automatic inactivity sweeps. |
| `/manualresetinactivity <user>` | Manage Messages | Manually reset a specific member's inactivity timer. |

### Engagement & Leaderboard Commands (`cogs/behavior.py`)

| Command | Permission | Description |
|---|---|---|
| `/emojirank <top/bottom>` | Everyone | View a paginated leaderboard of custom emoji usage counts across server messages. |
| `/reactionrank <top/bottom>` | Everyone | View a paginated leaderboard of custom emoji usage counts across message reactions. |

---

## 5. Administrator Workflows & Security Best Practices

1. **Server Hardening**:
   - Run `/crouton setup` immediately upon adding the bot to configure security logging and staff roles.
   - Deploy honeypot trap channels using `/sethoneypot` in hidden or restricted-looking staff areas to catch automated user token bots.
2. **Managing Roleplay Content**:
   - Utilize `/add_rp` with direct file attachments (`image_file`) for reliable permanent storage or hosted URLs (`image_url`).
   - Use `/manage_rp` for fine-grained moderation and content curation.
3. **Privacy Compliance**:
   - Okiner stores only explicitly submitted command inputs, family records, configuration settings, and activity telemetry in `rp.db`.
   - Regular chat message contents are never logged or stored. Consult [PRIVACY.md](PRIVACY.md) for full US/EU child privacy compliance disclosures.
