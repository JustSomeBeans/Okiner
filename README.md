# Okiner

Okiner is a Python based Discord bot project intended for server member interaction, community engagement, and roleplay-focused features.

The repository is currently set up with the structure needed to start development, including dependency management, environment configuration, and a minimal bot entrypoint.

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

After the bot starts, run `oki!sync` (owner only) in a server to register slash commands. Use `oki!sync global` to push them globally, or just `oki!sync` to push to the current server only (faster for testing).

## Commands

All commands are slash commands and only work inside servers. Management commands require **Manage Messages** permission.

### Roleplay

| Command | Description |
|---|---|
| `/rp <type> <target>` | Perform an RP interaction between you and a target member. Picks a random image, action text, and embed text from what's saved under that type. |

### Type Management *(mod only)*

| Command | Description |
|---|---|
| `/addtype <type>` | Register a new RP type for this server. Names must be alphanumeric with hyphens/underscores, max 64 characters. |
| `/removetype <type>` | Delete an RP type and everything saved under it (cascades to images, texts, and action texts). |
| `/listtype` | Show all RP types registered in this server. |

### Image Management *(mod only)*

| Command | Description |
|---|---|
| `/addimage <type> <url>` | Save an image URL under an RP type. Must be a direct `http`/`https` link. Imgur gallery links (`imgur.com`) are rejected — use the direct image link (`i.imgur.com`). |
| `/removeimage <type> <url>` | Remove a saved image URL from an RP type. |
| `/listimage <type>` | List all saved image URLs for an RP type. |

### Text Management *(mod only)*

| Command | Description |
|---|---|
| `/addtext <type> <text>` | Save an embed text template under an RP type. Max 1500 characters. Supports `{user}`, `{target}`, `{user_name}`, `{target_name}` placeholders. |
| `/removetext <type> <text>` | Remove a saved text template from an RP type. |
| `/listtext <type>` | List all saved text templates for an RP type. |

### Action Text Management *(mod only)*

Action texts appear as the bolded header line in the RP embed (e.g. *"Jane hugs Bob"*). They support the same placeholders as regular texts.

| Command | Description |
|---|---|
| `/addactiontext <type> <action_text>` | Save an action text template. You'll get a warning if `{user}` or `{target}` placeholders are missing, but you can still save it. Max 1500 characters. |
| `/removeactiontext <type> <action_text>` | Remove a saved action text template. |
| `/listactiontext <type>` | List all saved action text templates for an RP type. |

### Self Case Management *(mod only)*

Self cases handle what happens when a user targets themself with an RP command. RP types do not need to have a self case, and will work fine without one.

| Command | Description |
|---|---|
| `/addselfcase <type> <text> <action_text> <url>` | Set a custom response for when a user targets themselves. |
| `/removeselfcase <type>` | Remove the custom self targeting response for an RP type |
| `/listselfcase <type>` | Show the current self targeting response configured for an RP type |

### Placeholders

These tags are replaced dynamically when `/rp` is used:

| Tag | Replaced with |
|---|---|
| `{user}` | Mention of the person who ran `/rp` |
| `{target}` | Mention of the target member |
| `{user_name}` | Display name of the person who ran `/rp` |
| `{target_name}` | Display name of the target member |

## Owner Commands

| Command | Description |
|---|---|
| `oki!sync` | Sync slash commands to the current server. |
| `oki!sync global` | Sync slash commands globally (takes up to an hour to propagate). |