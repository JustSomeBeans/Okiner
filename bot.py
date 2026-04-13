from __future__ import annotations

# =============================================================================
# bot.py — OkinerBot class, intents, permissions, and invite URL helper
# -----------------------------------------------------------------------------
# Imported by:  main.py    → OkinerBot
# Imports from: config.py  → DB_PATH, SCHEMA_PATH
#               database.py → set_bot  (called in setup_hook to wire the pool)
#               discord    → discord.Intents, discord.Permissions
#               discord.ext.commands → commands.Bot
#               asqlite    → asqlite.Pool, asqlite.create_pool
#               urllib     → urlencode  (build_invite_url)
# Loads extension: cogs.rp_commands  (registered in setup_hook)
# =============================================================================

import logging
import os
from urllib.parse import urlencode

import asqlite
import discord
from discord.ext import commands

import database
from config import DB_PATH, SCHEMA_PATH

APPLICATION_ID = os.getenv("DISCORD_APPLICATION_ID")
# APPLICATION_ID is optional — without it the bot still works, it just won't log an invite URL at startup.

intents = discord.Intents.default()
intents.presences = True
intents.members = True
intents.message_content = True

requested_permissions = discord.Permissions(
    add_reactions=True,
    attach_files=True,
    change_nickname=True,
    embed_links=True,
    send_messages=True,
    send_messages_in_threads=True,
    use_external_emojis=True,
    use_external_stickers=True,
    use_application_commands=True,
    view_audit_log=True,
    view_channel=True,
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


class OkinerBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            intents=intents,
            command_prefix="oki!",
            application_id=int(APPLICATION_ID) if APPLICATION_ID else None,
            help_command=None,
        )
        self.db_pool: asqlite.Pool | None = None

    async def setup_hook(self) -> None:
        self.db_pool = await asqlite.create_pool(DB_PATH)
        database.set_bot(self)

        async with self.db_pool.acquire() as conn:
            # Enable foreign key enforcement — SQLite has it off by default.
            # We also do this per-connection in execute_query, but doing it here
            # ensures the schema creation itself (with the FK definition) is consistent.
            await conn.execute("PRAGMA foreign_keys = ON")
            # executescript runs the full SQL file — safe to call every startup
            # because every table uses CREATE TABLE IF NOT EXISTS.
            await conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
            await conn.commit()

        await self.load_extension("cogs.rp_commands")

    async def close(self) -> None:
        if self.db_pool is not None:
            await self.db_pool.close()
        await super().close()

    async def on_ready(self) -> None:
        logging.info("Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "unknown")

        if APPLICATION_ID:
            logging.info("Bot invite URL: %s", build_invite_url(APPLICATION_ID))