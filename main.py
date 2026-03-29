from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.parse import urlencode

import discord
from discord import app_commands
from dotenv import load_dotenv

import traceback
from discord.ext import commands
import asqlite
import typing

RP_FILE = "rp_data.json"  # TODO: make this configurable.
DEFAULT_RP_TYPES = ["hug", "bite", "hit"]  # TODO: revisit default categories and make dynamic eventually.

async def async_execute_query(query: str, params: tuple = ()) -> None:
    """Helper function to execute any db query, and commits them asynchronously."""
    async with bot.db_pool.acquire() as conn:
        await conn.execute(query, params)
        await conn.commit()

async def load_rp_data() -> dict[str, Any]:
    """Load RP data from disk, creating a minimal file if it does not exist yet."""
    # if not os.path.exists(RP_FILE):
    #     data: dict[str, Any] = {"servers": {}}
    #     save_rp_data(data)
    #     return data

    # with open(RP_FILE, "r", encoding="utf-8") as file_handle:
    #     data = json.load(file_handle)

    # if "servers" not in data or not isinstance(data["servers"], dict):
    #     data["servers"] = {}

    return None


# async def save_rp_data(user_id: int, guild_id: int, types: str, texts: str = None, url: str = None) -> None:
#    """Saves RP data into the rp.db database file."""
#    await async_execute_query("INSERT INTO roleplay (user_id, guild_id, url, texts, type) VALUES (?, ?, ?, ?, ?)", (user_id, guild_id, url, texts, types))

async def add_rp_type(guild_id: int, rp_type: str) -> None:
    await async_execute_query(
        "INSERT INTO rp_types (guild_id, type) VALUES (?, ?)",
        (guild_id, rp_type)
    )


async def add_rp_entry(user_id: int, guild_id: int, rp_type: str, text: str = None, url: str = None) -> None:
    await async_execute_query(
        "INSERT INTO roleplay_entries (user_id, guild_id, type, url, texts) VALUES (?, ?, ?, ?, ?)",
        (user_id, guild_id, rp_type, url, text)
    )

# Load local environment variables from `.env` so secrets stay out of source control.
load_dotenv()

# Keep logging simple and readable during development and deployment.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

TOKEN = os.getenv("DISCORD_TOKEN")
APPLICATION_ID = os.getenv("DISCORD_APPLICATION_ID")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set. Copy .env.example to .env and add your bot token.")

# These are the gateway intents the bot currently expects to use.
intents = discord.Intents.default()
intents.presences = True
intents.members = True
intents.message_content = True

# These permissions are used when generating the bot invite URL.
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


class OkinerBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(intents=intents, command_prefix="oki!", application_id=int(APPLICATION_ID) if APPLICATION_ID else None, help_command=None)

        # The command tree stores slash commands and handles sync with Discord.
        # ~~self.tree = app_commands.CommandTree(self)~~ No need to do this when subclassing commands.Bot

    # DB Pool initialization
    async def setup_hook(self):
        self.db_pool = await asqlite.create_pool("rp.db")

        async with self.db_pool.acquire() as conn:
            await conn.execute("PRAGMA foreign_keys = ON")

    async def close(self):
        if self.db_pool:
            await self.db_pool.close()
        await super().close()

    async def on_ready(self) -> None:
        logging.info("Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "unknown")

        if APPLICATION_ID:
            logging.info("Bot invite URL: %s", build_invite_url(APPLICATION_ID))


def build_invite_url(application_id: str) -> str:
    """Build the OAuth URL used to invite the bot with the current scopes and permissions."""
    query = urlencode(
        {
            "client_id": application_id,
            "scope": "bot applications.commands",
            "permissions": requested_permissions.value,
        }
    )
    return f"https://discord.com/oauth2/authorize?{query}"


async def rp_type_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Suggest RP types for the current guild using the new schema."""
    if not interaction.guild_id:
        return []

    pattern = f"%{current}%"
    async with bot.db_pool.acquire() as conn:
        result = await conn.execute(
            "SELECT type FROM rp_types WHERE guild_id = ? AND LOWER(type) LIKE LOWER(?) ORDER BY type LIMIT 25",
            (interaction.guild_id, pattern),
        )
        rows = await result.fetchall()

    return [app_commands.Choice(name=row[0], value=row[0]) for row in rows]


bot = OkinerBot()

# ----- COMMANDS -----

@bot.tree.command(name="ping", description="Check whether the bot is responding.")
async def ping(interaction: discord.Interaction) -> None:
    """Small health-check command used to confirm the bot is online."""
    await interaction.response.send_message("Pong!")


@bot.tree.command(name="rp", description="Perform an interaction between users.")
@app_commands.describe(rp_type="Which interaction to perform", target="Who to target")
@app_commands.autocomplete(rp_type=rp_type_autocomplete)
async def rp(interaction: discord.Interaction, rp_type: str, target: discord.Member) -> None:
    """
    Placeholder for the main RP command.

    The command is registered so the surrounding data and autocomplete flow can be
    developed safely, but the actual RP embed/content logic is intentionally left
    unfinished for a later pass.
    """
    await interaction.response.send_message(
        f"The `/rp` command for `{rp_type}` targeting {target.mention} is not implemented yet.",
        ephemeral=True,
    )


@bot.tree.command(name="addimage", description="Add an image URL to an RP type.")
@app_commands.guild_only()
@app_commands.autocomplete(rp_type=rp_type_autocomplete)
async def add_image(interaction: discord.Interaction, rp_type: str, url: str) -> None:
    rp_type = rp_type.strip().lower()
    """Store a new image URL for a guild-specific RP type."""
    async with bot.db_pool.acquire() as conn:
        result = await conn.execute(
            "SELECT 1 FROM rp_types WHERE guild_id = ? AND type = ?",
            (interaction.guild_id, rp_type),
        )
        exists = await result.fetchone()

        if not exists:
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return

    await add_rp_entry(interaction.user.id, interaction.guild_id, rp_type, url=url)
    await interaction.response.send_message(f"Added image to `{rp_type}`.", ephemeral=True)


@bot.tree.command(name="removeimage", description="Remove an image URL from an RP type.")
@app_commands.guild_only()
@app_commands.autocomplete(rp_type=rp_type_autocomplete)
async def remove_image(interaction: discord.Interaction, rp_type: str, url: str) -> None:
    """Remove an existing image URL from a guild-specific RP type using the new schema."""
    rp_type = rp_type.strip().lower()
    async with bot.db_pool.acquire() as conn:
        # Verify the RP type exists for this guild
        result = await conn.execute(
            "SELECT 1 FROM rp_types WHERE guild_id = ? AND type = ?",
            (interaction.guild_id, rp_type),
        )
        exists = await result.fetchone()
        if not exists:
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return

        # Verify the specific image entry exists
        result = await conn.execute(
            "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND user_id = ? AND type = ? AND url = ?",
            (interaction.guild_id, interaction.user.id, rp_type, url),
        )
        rp_entry = await result.fetchone()
        if not rp_entry:
            await interaction.response.send_message("That image URL was not found for this RP type.", ephemeral=True)
            return

    await async_execute_query(
        "DELETE FROM roleplay_entries WHERE guild_id = ? AND user_id = ? AND type = ? AND url = ?",
        (interaction.guild_id, interaction.user.id, rp_type, url),
    )
    await interaction.response.send_message(f"Removed image from `{rp_type}`.", ephemeral=True)


@bot.tree.command(name="addtext", description="Add a text template to an RP type.")
@app_commands.guild_only()
@app_commands.autocomplete(rp_type=rp_type_autocomplete)
async def add_text(interaction: discord.Interaction, rp_type: str, text: str) -> None:
    """Store a new text template for a guild-specific RP type using the new schema."""
    rp_type = rp_type.strip().lower()
    async with bot.db_pool.acquire() as conn:
        result = await conn.execute(
            "SELECT 1 FROM rp_types WHERE guild_id = ? AND type = ?",
            (interaction.guild_id, rp_type),
        )
        exists = await result.fetchone()

        if not exists:
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return

    await add_rp_entry(interaction.user.id, interaction.guild_id, rp_type, text=text)
    await interaction.response.send_message(f"Added text to `{rp_type}`.", ephemeral=True)

@bot.tree.command(name="removetext", description="Remove a text template from an RP type.")
@app_commands.guild_only()
@app_commands.autocomplete(rp_type=rp_type_autocomplete)
async def remove_text(interaction: discord.Interaction, rp_type: str, text: str) -> None:
    """Remove an existing text template from a guild-specific RP type using the new schema."""
    rp_type = rp_type.strip().lower()
    async with bot.db_pool.acquire() as conn:
        # Verify the RP type exists for this guild
        result = await conn.execute(
            "SELECT 1 FROM rp_types WHERE guild_id = ? AND type = ?",
            (interaction.guild_id, rp_type),
        )
        exists = await result.fetchone()
        if not exists:
            await interaction.response.send_message("Unknown RP type.", ephemeral=True)
            return

        # Verify the specific text entry exists
        result = await conn.execute(
            "SELECT 1 FROM roleplay_entries WHERE guild_id = ? AND user_id = ? AND type = ? AND texts = ?",
            (interaction.guild_id, interaction.user.id, rp_type, text),
        )
        rp_entry = await result.fetchone()
        if not rp_entry:
            await interaction.response.send_message("That text entry was not found for this RP type.", ephemeral=True)
            return

    await async_execute_query(
        "DELETE FROM roleplay_entries WHERE guild_id = ? AND user_id = ? AND type = ? AND texts = ?",
        (interaction.guild_id, interaction.user.id, rp_type, text),
    )
    await interaction.response.send_message(f"Removed text from `{rp_type}`.", ephemeral=True)

@bot.tree.command(name="addtype", description="Add a new RP type to the server.")
@app_commands.guild_only()
async def add_type(interaction: discord.Interaction, rp_type: str) -> None:
    """Add a new RP type to the server, which can then have text templates and image URLs added to it using the other commands."""
    rp_type = rp_type.strip().lower()
    if not rp_type:
        await interaction.response.send_message("RP type cannot be empty.", ephemeral=True)
        return
    if len(rp_type) > 64:
        await interaction.response.send_message("RP type too long.", ephemeral=True)
        return

    async with bot.db_pool.acquire() as conn:
        result = await conn.execute(
            "SELECT 1 FROM rp_types WHERE guild_id = ? AND type = ?",
            (interaction.guild_id, rp_type),
        )
        exists = await result.fetchone()
        if exists:
            await interaction.response.send_message("That RP type already exists.", ephemeral=True)
            return

    try:
        await add_rp_type(interaction.guild_id, rp_type)
    except Exception:
        logging.exception("Failed to add RP type")
        await interaction.response.send_message("Failed to add RP type.", ephemeral=True)
        return

    await interaction.response.send_message(f"Added new RP type `{rp_type}`.", ephemeral=True)


# ------ EVENTS --------
#Error handling for the bot, very minimal currently
#TODO: Identify future errors that will be produced by commands and handle them on a case-by-case basis, and add the corresponding code here
@bot.event

async def on_command_error(ctx: commands.Context, err) -> None:

    traceback_text = "".join(

        traceback.format_exception(type(err), err, err.__traceback__)

    )

    traceback_embed = discord.Embed(description=traceback_text, title=type(err))

    await ctx.reply(embed=traceback_embed)

# Slash/app command error handling
# Mirrors the classic command handler so we can see all errors in the same style, but also accounts for the differences in how responses work in the app command context.
# TODO: Could eventually unify logging and maybe add more verbose error messages instead of common traceback dumps, but this is a good start for now.
@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, err: app_commands.AppCommandError
) -> None:
    orig = getattr(err, "original", err)

    formatted = traceback.format_exception(type(orig), orig, orig.__traceback__)
    traceback_text = "".join(formatted)[:4096]

    embed = discord.Embed(
        title=type(orig).__name__,
        description=f"```py\n{traceback_text}\n```",
    )

    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception:
        logging.exception("Failed to send app command error reply")
        # Should be rare. Could happen if the interaction times out or permissions are missing.

# ----- SYNCING COMMANDS -----

@bot.command(name="sync")
@commands.is_owner()
async def sync(ctx, scope: typing.Optional[str] = "local"):
    """Sync slash commands, either globally or locally."""
    if scope == "global":
        synced = await bot.tree.sync()
        await ctx.reply(f"Global Synced {len(synced)} commands. May take some time.")
    elif scope == "local":
        bot.tree.copy_global_to(guild=ctx.guild)
        synced = await bot.tree.sync()
        await ctx.reply(f"Synced {len(synced)} commands for this guild!")
        

# ----- MAIN EVENT LOOP -----
def main() -> None:
    """Start the Discord client and block until the bot shuts down."""
    bot.run(TOKEN)
    


if __name__ == "__main__":
    main()
