from __future__ import annotations

import logging
import os

import discord
from dotenv import load_dotenv


load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set. Copy .env.example to .env and add your bot token.")

intents = discord.Intents.default()


class OkinerBot(discord.Client):
    async def on_ready(self) -> None:
        logging.info("Logged in as %s (ID: %s)", self.user, self.user.id if self.user else "unknown")

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return

        if message.content.strip().lower() == "!ping":
            await message.channel.send("Pong!")


def main() -> None:
    bot = OkinerBot(intents=intents)
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
