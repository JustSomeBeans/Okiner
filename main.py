from __future__ import annotations

# =============================================================================
# main.py — Entry point. Starts the bot and registers the owner !sync command.
# -----------------------------------------------------------------------------
# Dependency tree (what imports what):
#
#   main.py
#   └── bot.py              → OkinerBot (bot class + intents + permissions)
#       ├── config.py       → DB_PATH, SCHEMA_PATH
#       ├── database.py     → set_bot  (pool injected at startup)
#       │   └── bot.py      → OkinerBot  [TYPE_CHECKING only, no circular import]
#       └── cogs/
#           └── rp_commands.py  (loaded as extension in setup_hook)
#               ├── autocomplete.py → rp_type_autocomplete
#               │   └── utils.py   → normalize_rp_type
#               ├── checks.py      → moderator_only
#               ├── config.py      → MAX_EMBED_DESCRIPTION_LENGTH,
#               │                    MAX_TEXT_LENGTH, MAX_TYPE_LENGTH,
#               │                    MAX_URL_LENGTH
#               ├── database.py    → execute_query, fetch_one, fetch_column,
#               │                    rp_type_exists, add_rp_type, add_rp_entry
#               ├── utils.py       → normalize_rp_type, normalize_image_url,
#               │                    is_valid_image_url, truncate_for_embed,
#               │                    build_list_messages
#               │   └── config.py  → MAX_MESSAGE_LENGTH
#               └── views.py       → ActionTextConfirmView
#                   └── database.py → add_rp_entry
#
# Imports from: bot.py              → OkinerBot
#               discord.ext.commands → commands.Context, commands.is_owner,
#                                      commands.NotOwner
#               dotenv              → load_dotenv
#               logging, os         → stdlib
# =============================================================================

import logging
import os

from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

from bot import OkinerBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "DISCORD_TOKEN is not set. Copy .env.example to .env and add your bot token."
    )

bot = OkinerBot()


@bot.command(name="sync")
@commands.is_owner()
async def sync(ctx: commands.Context, scope: str = "local") -> None:
    scope = scope.lower()

    if scope == "global":
        synced = await bot.tree.sync()
        await ctx.reply(f"Global sync finished. {len(synced)} commands updated.")
        return

    if ctx.guild is None:
        await ctx.reply("Local sync only works inside a server.")
        return

    synced = await bot.tree.sync(guild=ctx.guild)
    await ctx.reply(
        f"Local sync finished for this server. {len(synced)} commands updated."
    )


@sync.error
async def sync_error(ctx: commands.Context, error: commands.CommandError) -> None:
    if isinstance(error, commands.NotOwner):
        await ctx.reply("That command is owner-only.")
        return

    logging.error(
        "Unhandled sync command error",
        exc_info=(type(error), error, error.__traceback__),
    )
    await ctx.reply("Sync failed. Check the logs for details.")


def main() -> None:
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
