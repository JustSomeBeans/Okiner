import discord
from discord import app_commands
from discord.ext import commands

from views import MarriageConfirmView

class FamilyCommands(commands.Cog):
    """All family commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="marry", description="Request to marry another user.")
    @app_commands.guild_only()
    @app_commands.describe(user="Who to marry")
    async def marry(self, interaction: discord.Interaction, user: discord.User):
        await interaction.response.send_message(view=MarriageConfirmView(interaction, user))

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FamilyCommands(bot))