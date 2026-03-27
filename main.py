from __future__ import annotations

import logging
import os
from urllib.parse import urlencode

from discord import app_commands
import discord
from dotenv import load_dotenv

# Load values from a local `.env` file into the process environment so we
# can keep secrets like the bot token out of source control.
load_dotenv()

# Configure simple console logging so startup events and errors are easy to see
# while developing locally or running the bot on a server.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# Read configuration from environment variables.
# `DISCORD_APPLICATION_ID` is optional for startup, but useful for building
# a correct invite URL and matching the bot to its Discord application.
TOKEN = os.getenv("DISCORD_TOKEN")
APPLICATION_ID = os.getenv("DISCORD_APPLICATION_ID")

# Stop immediately with a clear message if the required token is missing.
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set. Copy .env.example to .env and add your bot token.")

# Intents tell Discord which categories of events this bot wants to receive.
# This project needs presence updates, member events, and message content,
# so those privileged intents are explicitly enabled here.
intents = discord.Intents.default()
intents.presences = True
intents.members = True
intents.message_content = True

# These permissions mirror the intended bot capability set as closely as the
# Discord API allows when generating an OAuth invite URL.
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


class OkinerBot(discord.Client):
    def __init__(self) -> None:
        # `application_id` ties this client to the Discord application and is
        # especially useful when working with slash commands.
        super().__init__(intents=intents, application_id=int(APPLICATION_ID) if APPLICATION_ID else None)

        # `CommandTree` is the slash-command registry for discord.py.
        # We attach it to the client so commands can be declared below.
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        # This runs before `on_ready` and is the preferred place to sync
        # application commands with Discord.
        await self.tree.sync()

    async def on_ready(self) -> None:
        # `on_ready` fires when the bot has connected successfully and finished
        # preparing its internal cache.
        logging.info("Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "unknown")

        # Log an invite URL for convenience during setup if the application ID
        # has been provided in `.env`.
        if APPLICATION_ID:
            logging.info("Bot invite URL: %s", build_invite_url(APPLICATION_ID))


def build_invite_url(application_id: str) -> str:
    # Discord expects the scopes and permissions to be passed as query
    # parameters on the OAuth authorize URL.
    query = urlencode(
        {
            "client_id": application_id,
            "scope": "bot applications.commands",
            "permissions": requested_permissions.value,
        }
    )
    return f"https://discord.com/oauth2/authorize?{query}"


# Create one bot instance for the whole application.
bot = OkinerBot()


@bot.tree.command(name="ping", description="Check whether the bot is responding.")
async def ping(interaction: discord.Interaction) -> None:
    # Slash commands receive an interaction instead of a message object.
    # We reply directly to that interaction with a simple test response.
    await interaction.response.send_message("Pong!")


def main() -> None:
    # Start the Discord connection loop. This call blocks until the bot stops.
    bot.run(TOKEN)


if __name__ == "__main__":
    # This guard allows the file to be imported elsewhere later without
    # automatically starting the bot.
    main()
