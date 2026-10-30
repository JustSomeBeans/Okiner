from __future__ import annotations

# =============================================================================
# database.py — All SQLite access functions
# -----------------------------------------------------------------------------
# Imported by:  bot.py              → set_bot  (called in setup_hook)
#               views.py            → add_rp_entry
#               cogs/rp_commands.py → execute_query, fetch_one, fetch_column,
#                                     rp_type_exists, add_rp_type, add_rp_entry,
#                                     add_self_case
# Imports from: bot.py → OkinerBot  (TYPE_CHECKING only — avoids circular import;
#                                    runtime reference is injected via set_bot())
# =============================================================================

import sqlite3
from typing import TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from bot import OkinerBot


# Module-level reference set by bot.py after the bot is instantiated.
# We do it this way to avoid a circular import (bot.py imports database.py,
# so database.py can't import bot.py at module level). set_bot() is called
# in setup_hook once the pool is ready.
_bot: "OkinerBot | None" = None


@dataclass(frozen=True, slots=True)
class GuildConfig:
    guild_id: int
    log_channel_id: int | None
    honeypot_channel_id: int | None
    verified_role_id: int | None
    moderator_role_id: int | None
    inactivity_system_enabled: bool


_guild_config_cache: dict[int, GuildConfig | None] = {}


async def get_guild_config(guild_id: int) -> GuildConfig | None:
    """Single-process cache; every writer of guild_configs MUST call invalidate_guild_config after its write."""
    if guild_id in _guild_config_cache:
        return _guild_config_cache[guild_id]
    row = await fetch_one(
        "SELECT guild_id, log_channel_id, honeypot_channel_id, verified_role_id, moderator_role_id, inactivity_system_enabled FROM guild_configs WHERE guild_id = ?",
        (guild_id,)
    )
    if row is None:
        config = None
    else:
        config = GuildConfig(
            guild_id=row[0],
            log_channel_id=row[1],
            honeypot_channel_id=row[2],
            verified_role_id=row[3],
            moderator_role_id=row[4],
            inactivity_system_enabled=bool(row[5])
        )
    _guild_config_cache[guild_id] = config
    return config


def invalidate_guild_config(guild_id: int) -> None:
    _guild_config_cache.pop(guild_id, None)


INTEGRITY_TRIGGERS_SQL = """
DROP TRIGGER IF EXISTS trg_marriages_ordering;
CREATE TRIGGER trg_marriages_ordering BEFORE INSERT ON marriages
WHEN NEW.spouse1_id >= NEW.spouse2_id
BEGIN
    SELECT RAISE(ABORT, 'self or unordered marriage');
END;

DROP TRIGGER IF EXISTS trg_marriages_bigamy;
CREATE TRIGGER trg_marriages_bigamy BEFORE INSERT ON marriages
WHEN EXISTS (SELECT 1 FROM marriages WHERE spouse1_id IN (NEW.spouse1_id, NEW.spouse2_id) OR spouse2_id IN (NEW.spouse1_id, NEW.spouse2_id))
BEGIN
    SELECT RAISE(ABORT, 'already married');
END;

DROP TRIGGER IF EXISTS trg_marriages_parent_child;
CREATE TRIGGER trg_marriages_parent_child BEFORE INSERT ON marriages
WHEN EXISTS (SELECT 1 FROM children WHERE (child_id=NEW.spouse1_id AND parent_id=NEW.spouse2_id) OR (child_id=NEW.spouse2_id AND parent_id=NEW.spouse1_id))
BEGIN
    SELECT RAISE(ABORT, 'parent/child cannot marry');
END;

DROP TRIGGER IF EXISTS trg_children_self;
CREATE TRIGGER trg_children_self BEFORE INSERT ON children
WHEN NEW.child_id = NEW.parent_id
BEGIN
    SELECT RAISE(ABORT, 'self adoption');
END;

DROP TRIGGER IF EXISTS trg_children_reverse;
CREATE TRIGGER trg_children_reverse BEFORE INSERT ON children
WHEN EXISTS (SELECT 1 FROM children WHERE child_id=NEW.parent_id AND parent_id=NEW.child_id)
BEGIN
    SELECT RAISE(ABORT, 'reverse relationship');
END;

DROP TRIGGER IF EXISTS trg_children_spouse;
CREATE TRIGGER trg_children_spouse BEFORE INSERT ON children
WHEN EXISTS (SELECT 1 FROM marriages WHERE (spouse1_id=NEW.child_id AND spouse2_id=NEW.parent_id) OR (spouse1_id=NEW.parent_id AND spouse2_id=NEW.child_id))
BEGIN
    SELECT RAISE(ABORT, 'spouses cannot adopt each other');
END;
"""


def init_connection(conn: sqlite3.Connection) -> None:
    """Configure connection PRAGMAs on every pooled connection."""
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")


async def assert_connection_pragmas() -> None:
    """Assert that acquired pool connections have required PRAGMAs set correctly."""
    async with _pool().acquire() as conn:
        cursor = await conn.execute("PRAGMA foreign_keys")
        row = await cursor.fetchone()
        fk = row[0] if row else 0

        cursor = await conn.execute("PRAGMA busy_timeout")
        row = await cursor.fetchone()
        bt = row[0] if row else 0

        cursor = await conn.execute("PRAGMA journal_mode")
        row = await cursor.fetchone()
        jm = row[0] if row else ""

        cursor = await conn.execute("PRAGMA synchronous")
        row = await cursor.fetchone()
        sync = row[0] if row else 0

        if fk != 1 or bt < 5000 or str(jm).lower() != "wal" or sync != 1:
            raise RuntimeError(f"Connection pragmas invalid: foreign_keys={fk}, busy_timeout={bt}, journal_mode={jm}, synchronous={sync}")


def set_bot(bot: "OkinerBot") -> None:
    """Wire the database module to the running bot instance."""
    global _bot
    _bot = bot


def _pool():
    if _bot is None or _bot.db_pool is None:
        raise RuntimeError("Database pool is not available yet.")
    return _bot.db_pool


async def execute_query(query: str, params: tuple = ()) -> None:
    """Run a write query and commit it right away."""
    async with _pool().acquire() as conn:
        # PRAGMAs are applied by init_connection on every pooled connection.
        await conn.execute(query, params)
        await conn.commit()


async def execute_write(query: str, params: tuple = ()) -> int:
    """Run one write statement in a BEGIN IMMEDIATE transaction; return cursor.rowcount."""
    async with _pool().acquire() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = await conn.execute(query, params)
            count = cursor.get_cursor().rowcount
            await conn.commit()
            return count
        except BaseException:
            await conn.rollback()
            raise


async def fetch_one(query: str, params: tuple = ()) -> tuple | None:
    """Fetch a single database row."""
    async with _pool().acquire() as conn:
        result = await conn.execute(query, params)
        return await result.fetchone()


async def fetch_column(query: str, params: tuple = ()) -> list[str]:
    """Fetch the first column from all returned rows as a plain string list."""
    async with _pool().acquire() as conn:
        result = await conn.execute(query, params)
        rows = await result.fetchall()
    return [str(row[0]) for row in rows]


async def add_marriage(spouse1_id: int, spouse2_id: int, marriage_date: int) -> None:
    """Atomically create a marriage record with sorted pair, BEGIN IMMEDIATE, and rollback on error."""
    spouse1, spouse2 = sorted([spouse1_id, spouse2_id])
    async with _pool().acquire() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            await conn.execute(
                "INSERT INTO marriages (spouse1_id, spouse2_id, marriage_date) VALUES (?, ?, ?)",
                (spouse1, spouse2, marriage_date),
            )
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise


async def add_child(child_id: int, parent_id: int, adoption_date: int) -> None:
    """Atomically create an adoption record with cycle detection, BEGIN IMMEDIATE, and rollback on error."""
    async with _pool().acquire() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = await conn.execute(
                """
                WITH RECURSIVE ancestors(id, depth) AS (
                    SELECT parent_id, 1 FROM children WHERE child_id = ?
                    UNION ALL
                    SELECT c.parent_id, a.depth + 1
                    FROM children c
                    JOIN ancestors a ON c.child_id = a.id
                    WHERE a.depth < 50
                )
                SELECT 1 FROM ancestors WHERE id = ?
                """,
                (parent_id, child_id),
            )
            row = await cursor.fetchone()
            if row is not None or child_id == parent_id:
                raise sqlite3.IntegrityError("ancestry cycle")

            await conn.execute(
                "INSERT INTO children (child_id, parent_id, adoption_date) VALUES (?, ?, ?)",
                (child_id, parent_id, adoption_date),
            )
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise


async def find_multi_marriage_users() -> list[int]:
    """Find users appearing in more than one marriage row."""
    async with _pool().acquire() as conn:
        cursor = await conn.execute(
            """
            SELECT uid FROM (
                SELECT spouse1_id AS uid FROM marriages
                UNION ALL
                SELECT spouse2_id AS uid FROM marriages
            )
            GROUP BY uid
            HAVING COUNT(*) > 1
            ORDER BY uid
            """
        )
        rows = await cursor.fetchall()
        return [int(row[0]) for row in rows]


async def rp_type_exists(guild_id: int, rp_type: str) -> bool:
    """Return True if the given RP type exists for this guild."""
    row = await fetch_one(
        "SELECT 1 FROM rp_types WHERE guild_id = ? AND type = ?",
        (guild_id, rp_type),
    )
    return row is not None


async def add_rp_type(guild_id: int, rp_type: str) -> None:
    """Create a new RP type for the current server."""
    await execute_query(
        "INSERT INTO rp_types (guild_id, type) VALUES (?, ?)",
        (guild_id, rp_type),
    )


async def create_rp_type_with_entries(
    guild_id: int, user_id: int, rp_type: str, entries: list[dict]
) -> None:
    """Atomically create an RP type and its entries within a single BEGIN IMMEDIATE transaction."""
    seen = set()
    deduped_entries = []
    for entry in entries:
        key = (
            entry.get("case_type"),
            entry.get("url"),
            entry.get("text"),
            entry.get("action_text"),
        )
        if key not in seen:
            seen.add(key)
            deduped_entries.append(entry)

    async with _pool().acquire() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        try:
            await conn.execute(
                "INSERT INTO rp_types (guild_id, type) VALUES (?, ?)",
                (guild_id, rp_type),
            )
            for entry in deduped_entries:
                await conn.execute(
                    """
                    INSERT INTO roleplay_entries
                        (user_id, guild_id, type, case_type, url, texts, action_texts)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        guild_id,
                        rp_type,
                        entry.get("case_type"),
                        entry.get("url"),
                        entry.get("text"),
                        entry.get("action_text"),
                    ),
                )
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise


async def add_rp_entry(
    user_id: int,
    guild_id: int,
    rp_type: str,
    *,
    case_type: str = "standard",
    text: str | None = None,
    action_text: str | None = None,
    url: str | None = None,
) -> bool:
    """Store an entry tied to a server RP type. True if a row was inserted, False if an identical entry already existed."""
    rowcount = await execute_write(
        """
        INSERT OR IGNORE INTO roleplay_entries
            (user_id, guild_id, type, case_type, url, texts, action_texts)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, guild_id, rp_type, case_type, url, text, action_text),
    )
    return rowcount > 0


async def remove_rp_entry(
    guild_id: int,
    rp_type: str,
    case_type: str,
    column: str,
    value: str,
) -> None:
    """Remove a specific entry from roleplay_entries."""
    if column not in {"url", "texts", "action_texts"}:
        raise ValueError(f"Invalid column: {column!r}")
    await execute_query(
        f"DELETE FROM roleplay_entries WHERE guild_id = ? AND type = ? AND case_type = ? AND {column} = ?",
        (guild_id, rp_type, case_type, value),
    )


async def update_rp_entry(
    guild_id: int,
    rp_type: str,
    case_type: str,
    column: str,
    old_value: str,
    new_value: str,
) -> None:
    """Update a specific entry in roleplay_entries in place."""
    if column not in {"url", "texts", "action_texts"}:
        raise ValueError(f"Invalid column: {column!r}")
    await execute_query(
        f"UPDATE roleplay_entries SET {column} = ? WHERE guild_id = ? AND type = ? AND case_type = ? AND {column} = ?",
        (new_value, guild_id, rp_type, case_type, old_value),
    )
