from __future__ import annotations

# =============================================================================
# database.py — All SQLite access functions
# -----------------------------------------------------------------------------
# Imported by:  bot.py              → set_bot  (called in setup_hook)
#               views.py            → add_rp_entry
#               cogs/rp_commands.py → execute_query, fetch_one, fetch_column,
#                                     rp_type_exists, add_rp_type, add_rp_entry
# Imports from: bot.py → OkinerBot  (TYPE_CHECKING only — avoids circular import;
#                                    runtime reference is injected via set_bot())
# =============================================================================

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot import OkinerBot


# Module-level reference set by bot.py after the bot is instantiated.
_bot: "OkinerBot | None" = None


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
        await conn.execute("PRAGMA foreign_keys = ON")
        await conn.execute(query, params)
        await conn.commit()


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


async def add_rp_entry(
    user_id: int,
    guild_id: int,
    rp_type: str,
    *,
    case_type: str = "standard",
    text: str | None = None,
    action_text: str | None = None,
    url: str | None = None,
) -> None:
    """Store an entry tied to a server RP type."""
    await execute_query(
        """
        INSERT OR IGNORE INTO roleplay_entries
            (user_id, guild_id, type, case_type, url, texts, action_texts)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        # Previously the application pre checked for duplications in _add_text_entry,
        # _add_action_entry, and add_image, so under normal useage, you never reach
        # add_rp_entry with a duplicate, but there's a gap:
        # AddTextConfirmedView.confirm calls add_rp_entry directly with no duplicate check.
        # A user can trigger the warning, wait, then somhow submit a duplicate through
        # the confirm button. Rare, but not impossible. 
        # We switch to INSERT OR IGNORE and remove the false sense of safety. 
        # Low overhead, and saves a future headache across the whole database.
        (user_id, guild_id, rp_type, case_type, url, text, action_text),
    )
