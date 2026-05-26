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

All slash commands only work inside servers. Management commands require **Manage Messages** permission and are intended for moderators.

Most RP commands support autocomplete for RP type names. Commands that target another user also support member autocomplete and a special `everyone` target option.

### Roleplay

| Command | Description |
|---|---|
| `/rp <type> [target]` | Perform an RP interaction using the saved pools for that RP type. If a target is provided, Okiner uses the matching standard or selfcase content. If no target is provided, Okiner uses nullcase content. The bot picks a random action text, embed text, and standard-case image from what is saved. |

`/rp` behavior notes:

- The target is optional. Leaving it blank uses the nullcase flow.
- Targeting yourself uses the selfcase flow when selfcase entries exist. If a selfcase pool is missing, text and action text fall back to the standard pool.
- Images are always drawn from the standard image pool, even for selfcase and nullcase text/action variants.
- Using `everyone` keeps the interaction non-pinging and uses the standard case.
- Standard targeted RP messages include a temporary back button for 5 minutes.
- The back button is only usable once.
- If the original target was a specific member, only that member can press it.
- If the original target was `everyone`, any server member can press it.
- The back button never appears for selfcase or nullcase responses.

### Type Management *(mod only)*

| Command | Description |
|---|---|
| `/addtype <type>` | Register a new RP type for this server. Names are normalized to lowercase, must use only letters, numbers, hyphens, or underscores, and must stay within 64 characters. |
| `/removetype <type>` | Delete an RP type and everything saved under it, including standard, selfcase, and nullcase entries. |
| `/listtype` | Show all RP types registered in this server. |

### Image Management *(mod only)*

Images are type-level flavor and currently belong to the standard pool only.

| Command | Description |
|---|---|
| `/addimage <type> <url>` | Save an image URL under an RP type. Must be a valid `http` or `https` URL and stay within the bot's URL length limit. Imgur gallery links (`imgur.com`) are rejected; use a direct image link such as `i.imgur.com`. |
| `/removeimage <type> <url>` | Remove a saved image URL from an RP type. |
| `/listimage <type>` | List all saved image URLs for an RP type. |

### Standard Text Management *(mod only)*

Standard text entries are the default embed text pool for targeted RP. They support `{user}`, `{target}`, `{user_name}`, and `{target_name}` placeholders.

| Command | Description |
|---|---|
| `/addtext <type> <text>` | Save a standard embed text template under an RP type. Max 1500 characters. |
| `/removetext <type> <text>` | Remove a standard embed text template from an RP type. |
| `/listtext <type>` | List the standard embed text templates for an RP type. |

### Selfcase Text Management *(mod only)*

Selfcase text entries are used when a user targets themself with `/rp`.

| Command | Description |
|---|---|
| `/addselftext <type> <text>` | Save a selfcase embed text template under an RP type. Max 1500 characters. |
| `/removeselftext <type> <text>` | Remove a selfcase embed text template from an RP type. |
| `/listselftext <type>` | List the selfcase embed text templates for an RP type. |

### Nullcase Text Management *(mod only)*

Nullcase text entries are used when `/rp` is run without a target.

| Command | Description |
|---|---|
| `/addnulltext <type> <text>` | Save a nullcase embed text template under an RP type. Max 1500 characters. |
| `/removenulltext <type> <text>` | Remove a nullcase embed text template from an RP type. |
| `/listnulltext <type>` | List the nullcase embed text templates for an RP type. |

### Standard Action Text Management *(mod only)*

Action texts appear as the bolded header line in the RP embed, for example *"Jane hugs Bob"*. They support the same placeholders as regular texts.

| Command | Description |
|---|---|
| `/addactiontext <type> <action_text>` | Save a standard action text template. You'll get a warning if expected placeholders are missing, but you can still save it. Max 1500 characters. |
| `/removeactiontext <type> <action_text>` | Remove a standard action text template. |
| `/listactiontext <type>` | List the standard action text templates for an RP type. |

### Selfcase Action Text Management *(mod only)*

| Command | Description |
|---|---|
| `/addselfactiontext <type> <action_text>` | Save a selfcase action text template. Max 1500 characters. |
| `/removeselfactiontext <type> <action_text>` | Remove a selfcase action text template from an RP type. |
| `/listselfactiontext <type>` | List the selfcase action text templates for an RP type. |

### Nullcase Action Text Management *(mod only)*

| Command | Description |
|---|---|
| `/addnullactiontext <type> <action_text>` | Save a nullcase action text template. Max 1500 characters. |
| `/removenullactiontext <type> <action_text>` | Remove a nullcase action text template from an RP type. |
| `/listnullactiontext <type>` | List the nullcase action text templates for an RP type. |

### Case Notes

Selfcase behavior handles what happens when a user targets themself with an RP command. RP types do not need dedicated selfcase entries and will still work without them because text and action text fall back to the standard pool.

Nullcase behavior handles what happens when `/rp` is used without any target. Unlike selfcase, nullcase requires its own saved text and/or action text entries for the RP type to work without a target.

### Placeholders

These tags are replaced dynamically when `/rp` is used:

| Tag | Replaced with |
|---|---|
| `{user}` | Mention of the person who ran `/rp` |
| `{target}` | Mention of the target member |
| `{user_name}` | Display name of the person who ran `/rp` |
| `{target_name}` | Display name of the target member |

Notes:

- Missing expected action-text placeholders trigger a confirmation step instead of a hard rejection.
- Nullcase action texts are most useful with `{user}` and/or `{user_name}`, because there is no target in that flow.

## Owner Commands

| Command | Description |
|---|---|
| `oki!sync` | Sync slash commands to the current server. This is the default local sync mode and only works inside a server. |
| `oki!sync local` | Explicitly sync slash commands to the current server. |
| `oki!sync global` | Sync slash commands globally (takes up to an hour to propagate). |
