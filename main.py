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
import sqlite3
import typing

RP_FILE = "rp_data.json"  # TODO: make this configurable.
DEFAULT_RP_TYPES = ["hug", "bite", "hit"]  # TODO: revisit default categories and make dynamic eventually.


def load_rp_data() -> dict[str, Any]:
    """Load RP data from disk, creating a minimal file if it does not exist yet."""
    if not os.path.exists(RP_FILE):
        data: dict[str, Any] = {"servers": {}}
        save_rp_data(data)
        return data

    with open(RP_FILE, "r", encoding="utf-8") as file_handle:
        data = json.load(file_handle)

    if "servers" not in data or not isinstance(data["servers"], dict):
        data["servers"] = {}

    return data


def save_rp_data(data: dict[str, Any]) -> None:
    """Persist the RP data file to disk in a readable format."""
    with open(RP_FILE, "w", encoding="utf-8") as file_handle:
        json.dump(data, file_handle, indent=4)


def ensure_server_entry(data: dict[str, Any], guild_id: int) -> str:
    """Ensure the current guild has the expected default RP structure."""
    guild_id_str = str(guild_id)

    if guild_id_str not in data["servers"]:
        data["servers"][guild_id_str] = {
            rp_type: {"images": [], "texts": []} for rp_type in DEFAULT_RP_TYPES
        }

    return guild_id_str

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

    # Syncing every startup is not ideal because of ratelimits! Added a prefix-based command to sync instead.

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
    """Suggest RP types for the current guild, falling back to defaults when needed."""
    if interaction.guild is None:
        keys = DEFAULT_RP_TYPES
    else:
        data = load_rp_data()
        guild_id = ensure_server_entry(data, interaction.guild.id)
        save_rp_data(data)
        keys = list(data["servers"][guild_id].keys())

    return [
        app_commands.Choice(name=key, value=key)
        for key in keys
        if current.lower() in key.lower()
    ][:25]


bot = OkinerBot()


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
    """Store a new image URL for a guild-specific RP type."""
    data = load_rp_data()
    guild_id = ensure_server_entry(data, interaction.guild_id)
    rp_entry = data["servers"][guild_id].get(rp_type)

    if not rp_entry:
        await interaction.response.send_message("Unknown RP type.", ephemeral=True)
        return

    rp_entry["images"].append(url)
    save_rp_data(data)
    await interaction.response.send_message(f"Added image to `{rp_type}`.", ephemeral=True)


@bot.tree.command(name="removeimage", description="Remove an image URL from an RP type.")
@app_commands.guild_only()
@app_commands.autocomplete(rp_type=rp_type_autocomplete)
async def remove_image(interaction: discord.Interaction, rp_type: str, url: str) -> None:
    """Remove an existing image URL from a guild-specific RP type."""
    data = load_rp_data()
    guild_id = ensure_server_entry(data, interaction.guild_id)
    rp_entry = data["servers"][guild_id].get(rp_type)

    if not rp_entry:
        await interaction.response.send_message("Unknown RP type.", ephemeral=True)
        return

    try:
        rp_entry["images"].remove(url)
    except ValueError:
        await interaction.response.send_message("That image URL was not found for this RP type.", ephemeral=True)
        return

    save_rp_data(data)
    await interaction.response.send_message(f"Removed image from `{rp_type}`.", ephemeral=True)


@bot.tree.command(name="addtext", description="Add a text template to an RP type.")
@app_commands.guild_only()
@app_commands.autocomplete(rp_type=rp_type_autocomplete)
async def add_text(interaction: discord.Interaction, rp_type: str, text: str) -> None:
    """Store a new text template for a guild-specific RP type."""
    data = load_rp_data()
    guild_id = ensure_server_entry(data, interaction.guild_id)
    rp_entry = data["servers"][guild_id].get(rp_type)

    if not rp_entry:
        await interaction.response.send_message("Unknown RP type.", ephemeral=True)
        return

    rp_entry["texts"].append(text)
    save_rp_data(data)
    await interaction.response.send_message(f"Added text to `{rp_type}`.", ephemeral=True)

@bot.tree.command(name="removetext", description="Remove a text template from an RP type.")
@app_commands.guild_only()
@app_commands.autocomplete(rp_type=rp_type_autocomplete)
async def remove_text(interaction: discord.Interaction, rp_type: str, text: str) -> None:
    """Remove an existing text template from a guild-specific RP type."""
    data = load_rp_data()
    guild_id = ensure_server_entry(data, interaction.guild_id)
    rp_entry = data["servers"][guild_id].get(rp_type)

    if not rp_entry:
        await interaction.response.send_message("Unknown RP type.", ephemeral=True)
        return

    try:
        rp_entry["texts"].remove(text)
    except ValueError:
        await interaction.response.send_message("That text entry was not found for this RP type.", ephemeral=True)
        return

    save_rp_data(data)
    await interaction.response.send_message(f"Removed text from `{rp_type}`.", ephemeral=True)

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
