from __future__ import annotations

# =============================================================================
# autocomplete.py — app_commands autocomplete handlers
# -----------------------------------------------------------------------------
# Imported by:  cogs/rp_commands.py → rp_type_autocomplete,
#                                     rp_target_autocomplete, EVERYONE_TARGET
# Imports from: utils.py            → normalize_rp_type
#               discord             → discord.Interaction, discord.Member
#               discord.app_commands → app_commands.Choice
# =============================================================================

import discord
from discord import app_commands

from utils import normalize_rp_type

EVERYONE_TARGET = "everyone"


async def rp_type_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete RP types saved for the current guild."""
    if interaction.guild_id is None:
        return []

    bot = interaction.client
    if bot.db_pool is None:
        return []

    pattern = f"%{normalize_rp_type(current)}%"
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


async def rp_target_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete RP targets, including a safe everyone option."""
    guild = interaction.guild
    if guild is None:
        return []

    needle = current.strip().lower()
    choices: list[app_commands.Choice[str]] = []

    # Keep the special option visible without ever turning it into @everyone.
    if EVERYONE_TARGET.startswith(needle) or not needle:
        choices.append(app_commands.Choice(name=EVERYONE_TARGET, value=EVERYONE_TARGET))

    members: list[discord.Member] = []
    for member in guild.members:
        searchable_values = (
            member.display_name.lower(),
            member.name.lower(),
            str(member.id),
        )
        if needle and not any(needle in value for value in searchable_values):
            continue
        members.append(member)

    members.sort(
        key=lambda member: (
            not (
                needle
                and needle in member.display_name.lower()
                and needle in member.name.lower()
            ),
            member.display_name.lower(),
            member.name.lower(),
        )
    )
    for member in members[: 25 - len(choices)]:
        label = member.display_name
        if member.name != member.display_name:
            label = f"{member.display_name} (@{member.name})"
        choices.append(app_commands.Choice(name=label[:100], value=str(member.id)))

    return choices[:25]
