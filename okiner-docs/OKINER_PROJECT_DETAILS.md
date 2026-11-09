# Okiner Project Technical Specification & Architecture Guide

Last updated: November 9, 2026

## 1. Module Map

### Core modules
- **`main.py`**: loads `.env`, creates `OkinerBot`, and defines the owner-only `oki!sync` prefix command (replies with `ctx.send`).
- **`bot.py`**: `OkinerBot`, intents, requested permissions, invite URL helper, and `OkinerTree` (a `CommandTree` with a guild-only check and a central error handler). `setup_hook` runs migrations in a thread **before** creating the connection pool, then wires `database.set_bot`, asserts connection PRAGMAs, warns about legacy multi-marriage rows, and loads the cogs. `close()` closes the cogs first (so they can flush) and the pool afterwards.
- **`migrations.py`**: versioned migrations on a plain `sqlite3` connection (see section 3).
- **`database.py`**: connection init hook, query helpers, atomic write helpers, the integrity triggers, and the guild config cache.
- **`rp_schema.sql`**: table definitions (`CREATE TABLE IF NOT EXISTS` only; no indexes, no triggers).
- **`config.py`**: constants (length limits, case names, database path).
- **`utils.py`**: placeholder substitution, image URL checks, truncation, list chunking.
- **`autocomplete.py`**: RP type and target autocomplete (LIKE wildcards escaped).
- **`checks.py`**: `has_manage_messages(interaction)` and `moderator_only()`; both use `interaction.permissions` (channel-aware).
- **`alt_detector.py`**: scoring for `/scan`.
- **`views.py`**: all `discord.ui` views, modals, and containers.

### Cogs
- **`cogs/rp_commands.py`**: `/rp`, `/add_rp`, `/edit_rp`, `/manage_rp`.
- **`cogs/family_commands.py`**: `/marry`, `/divorce`, `/adopt`, `/disown`, `/familytree`.
- **`cogs/moderation.py`**: `/crouton setup`, `/crouton clear`, `/crouton help`, `/crouton uptime`, `/scan`, `/sethoneypot`, scan allowlist, honeypot listener.
- **`cogs/behavior.py`**: batched activity tracking, emoji and reaction counters, leaderboards, cleanup listeners.

---

## 2. Database Schema (`rp_schema.sql`)

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
    reaction_uses INTEGER DEFAULT 0,
    PRIMARY KEY (guild_id, emoji_id)
);
```

Notes:
- `marriages` and `children` are **global** by design (no `guild_id`).
- Unused, reserved `member_behavior` columns: `staff_directed_messages`, `daily_message_counts`, `daily_reaction_activity`, `voice_session_started_at`, `invited_by`, `invite_code`.
- Migration 2 adds the unique expression index `ux_roleplay_entries_content` on `(guild_id, type, case_type, COALESCE(url,''), COALESCE(texts,''), COALESCE(action_texts,''))`. The primary key alone cannot deduplicate because NULLs in a SQLite primary key are distinct. Any future migration that rebuilds `roleplay_entries` must recreate this index. Indexes must not live in `rp_schema.sql`, because the schema runs before pending migrations on old databases.
- Timestamps in `marriage_date` / `adoption_date` are integers stored in TEXT columns.

---

## 3. Migrations & Backups (`migrations.py`)

`run_migrations(db_path, schema_sql)` runs synchronously on a raw `sqlite3` connection before the pool exists:

1. Open the database with the standard PRAGMAs; read `PRAGMA user_version`. A value higher than the code knows aborts startup.
2. If migrations are pending and the database already has tables, write a backup with SQLite's backup API (`rp.db.bak-<UTC timestamp>`, integrity-checked). If the backup fails, nothing is migrated.
3. Run the schema script.
4. For each pending migration: `BEGIN IMMEDIATE`; drop the six integrity triggers; run the migration; recreate the triggers; set `user_version`; `COMMIT`. Any error rolls everything back, including the trigger drop.
5. With nothing pending, only the triggers are reinstalled.

Dropping triggers around each migration matters because SQLite rewrites trigger bodies when a table is renamed. Migrations use individual statements because `executescript` commits any open transaction.

Current versions: **1** (legacy layout upgrades: `case_type` column, `rp_self_cases` folded into `roleplay_entries` as `selfcase`, unique constraints on `children` and `marriages`), **2** (duplicate cleanup keeping the lowest `rowid`, then the unique index).

---

## 4. Connection Management

- `asqlite.create_pool(DB_PATH, init=database.init_connection)`. The init hook runs on every pooled connection and sets `foreign_keys=ON`, `busy_timeout=5000`, `journal_mode=WAL`, `synchronous=NORMAL`. Startup asserts the values.
- `database.py` reaches the pool through `set_bot(bot)` to avoid a circular import.
- Multi-statement writes use `BEGIN IMMEDIATE` with commit and rollback: `add_marriage`, `add_child`, `create_rp_type_with_entries`, `execute_write` (returns the row count), and `execute_batch` (several `executemany` statements in one transaction).
- Tests that use the pool must use a temporary file database, not `:memory:`, because each pooled connection would get its own empty in-memory database.

---

## 5. Integrity Rules

Six SQLite triggers, installed by `database.INTEGRITY_TRIGGERS_SQL`, reject inserts that would create: an unordered or self marriage, a second marriage for either spouse, a parent-child marriage, a self adoption, a reverse parent-child record, or an adoption between spouses. `add_child` also rejects ancestry cycles (depth capped at 50). Violations surface as `sqlite3.IntegrityError`. Existing bad rows are never deleted automatically; startup logs a warning listing users that appear in several marriage rows.

`/divorce` and `/disown` delete first, check the row count, and only then announce, so a database failure never announces success.

---

## 6. Caching and Batching

- **Guild config cache** (`database.get_guild_config`): in-process dict of frozen `GuildConfig` dataclasses, `None` cached too. Every writer of `guild_configs` must call `invalidate_guild_config` after its write. The honeypot listener, `/scan` and `/crouton setup` read through the cache; `/crouton clear` does not read it, it writes with `database.execute_write` and then calls `invalidate_guild_config`.
- **Behavior batching** (`cogs/behavior.py`): messages and reactions increment in-memory counters; a 15 second `tasks.loop` and `cog_unload` flush them in one transaction with additive upserts (`MAX` for last-active time). The counters are swapped out before the write so concurrent increments are not lost; a failed flush merges back. Honeypot-channel messages are not counted. Join time comes from `member.joined_at`.
- A flush already in flight can re-insert a row for a member or server removed at the same moment. This is accepted.

---

## 7. Views and Interaction Safety (`views.py`)

- Every `View` has a `message` attribute and a guarded `on_timeout` (disables items; edit errors are swallowed). Hand-offs between views call `stop()` so stale timeouts cannot overwrite newer messages.
- Management views (`AddRPOptionsView`, `EditRPOptionsView`, `ManageRPView`, `ManageRPEntriesView`) and their modals check the original user **and** that the user still has Manage Messages (`interaction.permissions`).
- `ManageRPView` pages RP types 25 at a time. `ManageRPEntriesView` shows image entries as embeds with a text fallback if the embed fails.
- `RPBackView` allows one use per targeted message.
- Marriage and adoption containers use a single-resolution flag (double clicks cannot run twice), release their pending-proposal key on accept, reject, or timeout, and send follow-ups with narrowly scoped `allowed_mentions`.
- `/marry` and `/adopt` have a 30 second per-user cooldown and a pending-proposal set per (kind, proposer, target).

---

## 8. Roleplay Pipeline

1. `_resolve_target`: blank target is `nullcase`, self is `selfcase`, otherwise `standard`; `everyone` is a plain text target.
2. Text and action pools come from the active case and fall back to `standard` when empty. Images always come from the standard pool.
3. `apply_placeholders` substitutes `{user}`, `{target}`, `{user_name}`, `{target_name}` in a single pass, so substituted text is never re-scanned. Display names are markdown- and mention-escaped; `{user}` and `{target}` stay as mentions. All messages use `allowed_mentions.none()`.
4. The action line is truncated before being wrapped in bold.
5. If sending with an image fails, the message is retried without it.

`/add_rp` validates everything first and writes the type and all entries in one transaction. If the action text lacks the expected tags, a confirm view holds the full payload and nothing is written until confirmation.

---

## 9. Family Tree

Relationship tables are global, so the tree shows only people who are members of the current server (the target is always included), nearest relatives first, capped at 40 nodes with a note when truncated. Layout and drawing run in a worker thread; display names are resolved before the thread starts. Fonts are tried in order: DejaVu Sans, Liberation Sans, Arial, then Pillow's default. Any failure sends "Couldn't render the family tree."

---

## 10. Developer Guidelines

- **New cog**: create `cogs/my_cog.py` with `async def setup(bot)` and add `await self.load_extension("cogs.my_cog")` in `bot.py`.
- **Schema change**: add a numbered migration in `migrations.py` (never a bare `ALTER` at startup), keep it idempotent, update tests that assert the version list, and recreate the unique index if you rebuild `roleplay_entries`.
- **Writers of `guild_configs`** must invalidate the cache.
- **Tests**: `unittest` only (`.venv/bin/python3 -m unittest discover`), plus `pyflakes`. Use temp-file databases, construct views inside async tests, and keep line endings as committed (`database.py`, `bot.py`, and `checks.py` are CRLF).
- **Errors**: unhandled command errors are handled by `OkinerTree.on_error`, which never shows exception text to users.
