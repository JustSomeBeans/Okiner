from __future__ import annotations

# =============================================================================
# autocomplete.py — app_commands autocomplete handlers
# -----------------------------------------------------------------------------
# Imported by:  cogs/rp_commands.py → rp_type_autocomplete
# Imports from: utils.py            → normalize_rp_type
#               discord             → discord.Interaction
#               discord.app_commands → app_commands.Choice
# =============================================================================

import discord
from discord import app_commands

from utils import normalize_rp_type


async def rp_type_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete handler that queries saved RP types for the current guild."""
    if interaction.guild_id is None:
        return []

    bot = interaction.client
    if bot.db_pool is None:
        return []

    pattern = f"%{normalize_rp_type(current)}%"
    # We normalize current so "HUG" matches the stored "hug" — normalize_rp_type lowercases it.
    # The %...% pattern means it'll match anywhere in the type name, not just prefixes.
    async with bot.db_pool.acquire() as conn:
        result = await conn.execute(
            """
            SELECT type
            FROM rp_types
            WHERE guild_id = ? AND LOWER(type) LIKE ?
            ORDER BY type COLLATE NOCASE
            LIMIT 25
            """,
            (interaction.guild_id, pattern),
        )
        rows = await result.fetchall()

    return [app_commands.Choice(name=row[0], value=row[0]) for row in rows]