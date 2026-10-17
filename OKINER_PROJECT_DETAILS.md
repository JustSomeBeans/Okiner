# Okiner Project Technical Specification & Architecture Guide

Last updated: October 17, 2026

## 1. Architectural Blueprint & Module Map

Okiner is engineered around a clean, decoupled architecture built on `discord.py` and asynchronous SQLite storage (`asqlite`).

### Core Modules
- **`main.py`**: Application bootstrap, environment loading, instantiation of `OkinerBot`, and prefix command router for deployment sync (`oki!sync` and `oki!sync global`).
- **`bot.py`**: Defines the `OkinerBot` subclass (`commands.Bot`), which sets up the asynchronous SQLite connection pool in `setup_hook()`, links `database.set_bot(self)`, and loads all extension cogs (`cogs.rp_commands`, `cogs.family_commands`, `cogs.moderation`, `cogs.behavior`).
- **`database.py`**: Asynchronous database abstraction layer providing helper functions (`execute_query`, `fetch_one`, `fetch_column`) and domain-specific queries (`rp_type_exists`, `add_rp_type`, `add_rp_entry`, `remove_rp_entry`, `update_rp_entry`).
- **`rp_schema.sql`**: Authoritative relational schema defining tables, primary keys, indexes, and foreign key cascades (`PRAGMA foreign_keys = ON`).
- **`config.py`**: Global constants including maximum string lengths (`MAX_TEXT_LENGTH = 1500`, `MAX_URL_LENGTH = 1000`, `MAX_TYPE_LENGTH = 64`), case identifiers (`STANDARD_CASE = "standard"`, `SELF_CASE = "selfcase"`, `NULL_CASE = "nullcase"`), and string targets.
- **`utils.py`**: Utility engine handling `PlaceholderTarget` dataclass, placeholder replacement (`{user}`, `{target}`, `{user_name}`, `{target_name}`), image URL sanitization and validation (`is_valid_image_url`, `normalize_image_url`), and smart embed text truncation.
- **`autocomplete.py`**: App command autocomplete handlers (`rp_type_autocomplete`, `rp_target_autocomplete`) providing fast member and roleplay type lookup.
- **`checks.py`**: Security decorators including `@moderator_only()` restricting sensitive commands to users with `Manage Messages` or `Administrator` permissions.
- **`alt_detector.py`**: Pure Python trust and alt scoring engine analyzing account creation timestamps, default avatars, and avatar hashes to generate visual scan card embeds (`generate_scan_card`).

### Extension Cogs (`cogs/`)
- **`cogs/rp_commands.py`**: Roleplay engine powering `/rp`, `/add_rp`, `/edit_rp`, and `/manage_rp`.
- **`cogs/family_commands.py`**: Family relationship workflows powering `/marry`, `/divorce`, `/adopt`, `/disown`, and `/familytree`.
- **`cogs/moderation.py`**: Crouton security suite powering `/crouton setup`, `/scan`, `/sethoneypot`, allowlist management, and honeypot ban enforcement.
- **`cogs/behavior.py`**: Activity tracking task (`inactivity_sweep`), message counting, and custom emoji/reaction leaderboards (`/emojirank`, `/reactionrank`).

---

## 2. SQLite Database Schema (`rp_schema.sql`)

The SQLite database (`rp.db`) is structured with strict referential integrity:

```sql
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS rp_types (
    guild_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    PRIMARY KEY (guild_id, type)
);

CREATE TABLE IF NOT EXISTS roleplay_entries (
    user_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    case_type TEXT NOT NULL DEFAULT 'standard',
    url TEXT,
    texts TEXT,
    action_texts TEXT,
    PRIMARY KEY (user_id, guild_id, type, case_type, url, texts, action_texts),
    FOREIGN KEY (guild_id, type)
        REFERENCES rp_types(guild_id, type)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS rp_self_cases (
    guild_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    texts TEXT,
    action_texts TEXT,
    url TEXT,
    PRIMARY KEY (guild_id, type),
    FOREIGN KEY (guild_id, type)
        REFERENCES rp_types(guild_id, type)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS children (
    offspring_id INTEGER PRIMARY KEY AUTOINCREMENT, 
    child_id INTEGER UNIQUE NOT NULL, 
    parent_id INTEGER NOT NULL,
    adoption_date TEXT
);

CREATE TABLE IF NOT EXISTS marriages (
    marriage_id INTEGER PRIMARY KEY,
    spouse1_id INTEGER UNIQUE NOT NULL,
    spouse2_id INTEGER UNIQUE NOT NULL,
    marriage_date TEXT,
    UNIQUE (spouse1_id, spouse2_id)
);

CREATE TABLE IF NOT EXISTS guild_configs (
    guild_id INTEGER PRIMARY KEY,
    log_channel_id INTEGER NULL,
    honeypot_channel_id INTEGER NULL,
    verified_role_id INTEGER NULL,
    moderator_role_id INTEGER NULL,
    inactivity_system_enabled BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scan_channels (
    guild_id INTEGER,
    channel_id INTEGER,
    PRIMARY KEY (guild_id, channel_id)
);

CREATE TABLE IF NOT EXISTS member_behavior (
    guild_id INTEGER,
    user_id INTEGER,
    joined_at INTEGER,
    total_messages INTEGER DEFAULT 0,
    staff_directed_messages INTEGER DEFAULT 0,
    daily_message_counts TEXT,
    daily_reaction_activity TEXT,
    voice_session_started_at INTEGER NULL,
    invited_by INTEGER NULL,
    invite_code TEXT NULL,
    last_active_at INTEGER,
    inactivity_status TEXT NULL,
    inactivity_reset_at INTEGER NULL,
    PRIMARY KEY (guild_id, user_id)
);

CREATE TABLE IF NOT EXISTS guild_emojis (
    guild_id INTEGER,
    emoji_id INTEGER,
    message_uses INTEGER DEFAULT 0,
    reaction_uses INTEGER REACTIONS DEFAULT 0,
    PRIMARY KEY (guild_id, emoji_id)
);
```

---

## 3. Database Pool Wiring & Connection Management

To prevent circular import dependencies between `bot.py` and `database.py`:
1. **Module Injection (`database.py`)**: `database.py` defines `_bot: OkinerBot | None = None` and `set_bot(bot)`.
2. **Initialization (`bot.py`)**: During `setup_hook()`, `OkinerBot` instantiates the `asqlite` pool (`self.db_pool = await asqlite.create_pool("rp.db")`) and calls `database.set_bot(self)`.
3. **Foreign Keys Enforcement**: Because `asqlite` pool connections do not automatically inherit session PRAGMAs across pool checkouts, every database helper function explicitly executes `await conn.execute("PRAGMA foreign_keys = ON")` upon acquiring a connection.

---

## 4. Discord UI View & Container Architectures (`views.py`)

Okiner implements advanced `discord.ui` components for stateful interaction flows:
- **`AddRPOptionsView`**: Interactive configuration view enabling moderators to cycle through 4 case modes (`Standard Only`, `Standard + Selfcase`, `Standard + Nullcase`, `Standard + Self + Null`) prior to modal invocation.
- **`AddRPModal`**: Stateful Discord modal dynamically sizing its text inputs (Standard text/action, optional Selfcase text, optional Nullcase text) based on the chosen mode.
- **`EditRPOptionsView` & `EditRPModal`**: Dropdown selection menu and input modal for appending entries to specific data pools of an existing roleplay type.
- **`ManageRPView` & `ManageRPEntriesView`**: Multi-step interactive browser providing pagination (`Prev`, `Next`), entry editing (`Edit`), entry deletion (`Delete`), category switching (`« Back`), type removal (`🗑️ Remove RP Type`), and breadcrumb navigation (`« Back to Types`).
- **`RPBackView`**: Interactive button attached to roleplay embed responses allowing users to trigger reciprocal actions.
- **`MarryContainer` & `AdoptContainer`**: Interactive acceptance/rejection containers managing family proposals.

---

## 5. Case-Flow Logic & Dual Image Processing

### Case Resolution Pipeline (`_execute_rp`)
1. **Target Identification**: `_resolve_target` evaluates the target parameter:
   - If missing or blank -> `NULL_CASE`.
   - If targeting self -> `SELF_CASE`.
   - Otherwise -> `STANDARD_CASE`.
2. **Pool Fetching (`_fetch_case_entries`)**:
   - Queries entries for the active `case_type`.
   - Automatically falls back to `STANDARD_CASE` if `SELF_CASE` or `NULL_CASE` pools are empty.
   - Images are always retrieved from the `STANDARD_CASE` image pool as type-level flavor.
3. **Placeholder Substitution**: Replaces template variables (`{user}`, `{target}`, `{user_name}`, `{target_name}`) with rich member mentions and clean display names.

### Dual Image Input Architecture (`/add_rp`)
- **Parameters**: `image_url: str | None` and `image_file: discord.Attachment | None`.
- **XOR Validation**: Enforces strict mutual exclusivity. If neither or both are provided, execution halts with an ephemeral error message.
- **Processing**:
   - If `image_file` is provided, validates content type (`image/png`, `image/jpeg`, `image/webp`, `image/gif`) and captures `image_file.url`.
   - If `image_url` is provided, normalizes URL, rejects non-direct Imgur links, validates against `is_valid_image_url`, and checks maximum length constraints.

---

## 6. Developer Maintenance & Extension Guidelines

- **Adding New Cogs**: Implement your cog in `cogs/my_cog.py`, expose an asynchronous `setup(bot)` function, and register it in `bot.py` via `await self.load_extension("cogs.my_cog")`.
- **Database Migrations**: Add schema definitions to `rp_schema.sql` and include idempotent table/column creation checks in `bot.py` during startup.
- **Error Propagation**: Always decorate app commands with local error handlers (`cog_app_command_error`) or rely on global error handling to ensure users receive clear, helpful ephemeral feedback.
