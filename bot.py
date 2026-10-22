from __future__ import annotations

# =============================================================================
# bot.py — OkinerBot class, intents, permissions, and invite URL helper
# -----------------------------------------------------------------------------
# Imported by:  main.py    → OkinerBot
# Imports from: config.py  → DB_PATH, SCHEMA_PATH
#               database.py → set_bot  (called in setup_hook to wire the pool)
#               migrations.py → run_migrations (called in setup_hook)
#               discord    → discord.Intents, discord.Permissions
#               discord.ext.commands → commands.Bot
#               asqlite    → asqlite.Pool, asqlite.create_pool
#               urllib     → urlencode  (build_invite_url)
# Loads extension: cogs.rp_commands  (registered in setup_hook)
# =============================================================================

import asyncio
import logging
import os
from urllib.parse import urlencode

import asqlite
import discord
from discord import app_commands
from discord.ext import commands

import database
import migrations
from config import DB_PATH, SCHEMA_PATH

APPLICATION_ID = os.getenv("DISCORD_APPLICATION_ID")
# APPLICATION_ID is optional — without it the bot still works, it just won't log an invite URL at startup.

intents = discord.Intents.default()
intents.presences = False  # not needed
intents.members = True     # member lookup/autocomplete and join data
intents.message_content = True  # emoji tracking and the oki!sync prefix command

requested_permissions = discord.Permissions(
    attach_files=True,
    embed_links=True,
    send_messages=True,
    send_messages_in_threads=True,
    use_external_emojis=True,
    use_application_commands=True,
    view_channel=True,
    ban_members=True,
    manage_messages=True,
)


def build_invite_url(application_id: str) -> str:
    query = urlencode(
        {
            "client_id": application_id,
            "scope": "bot applications.commands",
            "permissions": requested_permissions.value,
        }
    )
    return f"https://discord.com/oauth2/authorize?{query}"


class OkinerTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            if interaction.type is discord.InteractionType.application_command:
                if not interaction.response.is_done():
                    try:
                        await interaction.response.send_message(
                            "This command only works in a server.", ephemeral=True
                        )
                    except discord.HTTPException:
                        pass
            return False
        return True

    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        original = error.original if isinstance(error, app_commands.CommandInvokeError) else error

        if isinstance(original, app_commands.MissingPermissions):
            msg = "You don't have permission to do that."
        elif isinstance(original, app_commands.BotMissingPermissions):
            msg = "I'm missing permissions I need for that."
        elif isinstance(original, app_commands.NoPrivateMessage):
            msg = "This command only works in a server."
        elif isinstance(original, app_commands.CommandOnCooldown):
            msg = f"Slow down. Try again in {original.retry_after:.0f}s."
        elif isinstance(original, app_commands.CheckFailure):
            msg = "You can't use that command here."
        else:
            cmd_name = interaction.command.qualified_name if interaction.command else "unknown"
            logging.error(
                "Unhandled application command error in %r",
                cmd_name,
                exc_info=(type(original), original, original.__traceback__),
            )
            msg = "Something went wrong. Please try again later."

        if not interaction.response.is_done():
            try:
                await interaction.response.send_message(msg, ephemeral=True)
            except discord.HTTPException:
                logging.warning("Failed to send ephemeral error response")
        else:
            try:
                await interaction.followup.send(msg, ephemeral=True)
            except discord.HTTPException:
                logging.warning("Failed to send ephemeral error followup")


class OkinerBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            intents=intents,
            command_prefix="oki!",
            application_id=int(APPLICATION_ID) if APPLICATION_ID else None,
            help_command=None,
            tree_cls=OkinerTree,
        )
        self.db_pool: asqlite.Pool | None = None

    async def setup_hook(self) -> None:
        schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
        applied = await asyncio.to_thread(migrations.run_migrations, DB_PATH, schema_sql)
        if applied:
            logging.info("Applied database migrations: %s", applied)

        self.db_pool = await asqlite.create_pool(DB_PATH, init=database.init_connection)
        database.set_bot(self)
        await database.assert_connection_pragmas()

        try:
            multi_users = await database.find_multi_marriage_users()
            if multi_users:
                preview = multi_users[:20]
                logging.warning(
                    "Found %d users appearing in multiple marriage rows (from before integrity triggers existed; first 20: %s). Manual review required.",
                    len(multi_users),
                    preview,
                )
        except Exception:
            logging.exception("Failed to check for multi-marriage users during startup")

        await self.load_extension("cogs.rp_commands")
        await self.load_extension("cogs.family_commands")
        await self.load_extension("cogs.moderation")
        await self.load_extension("cogs.behavior")

    async def close(self) -> None:
        if self.db_pool is not None:
            await self.db_pool.close()
        await super().close()

    async def on_ready(self) -> None:
        logging.info(
            "Logged in as %s (ID: %s)",
            self.user,
            self.user.id if self.user else "unknown",
        )

        if APPLICATION_ID:
            logging.info("Bot invite URL: %s", build_invite_url(APPLICATION_ID))
