from __future__ import annotations

# =============================================================================
# checks.py — Reusable app_commands permission checks
# -----------------------------------------------------------------------------
# Imported by:  cogs/rp_commands.py → moderator_only
# Imports from: discord             → discord.Interaction
#               discord.app_commands → app_commands.Check, NoPrivateMessage,
#                                      MissingPermissions, app_commands.check
# =============================================================================

import discord
from discord import app_commands


def moderator_only() -> app_commands.Check:
    """Restrict management commands to members with the Manage Messages permission.

    This is used alongside @app_commands.default_permissions() on every mod command.
    default_permissions controls Discord's UI visibility but can be overridden by server
    admins — this check is the actual gate that runs at command invocation time.
    """
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            raise app_commands.NoPrivateMessage()

        # guild_permissions is only available on Member, not User (e.g. in DMs).
        # getattr with a default lets us handle both without an isinstance check.
        permissions = getattr(interaction.user, "guild_permissions", None)
        if permissions and permissions.manage_messages:
            return True

        raise app_commands.MissingPermissions(["manage_messages"])

    return app_commands.check(predicate)