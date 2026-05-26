import discord
from discord import app_commands
from discord.ext import commands
from database import add_rp_entry, execute_query, fetch_one
from views import MarriageConfirmView, AdoptionConfirmView

class FamilyCommands(commands.Cog):
    """All family commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="marry", description="Propose to marry another user.")
    @app_commands.guild_only()
    @app_commands.describe(user="Who to marry")
    async def marry(self, interaction: discord.Interaction, user: discord.User):
        if user.id == interaction.user.id:
            await interaction.response.send_message("You can't marry yourself... </3")
            return

        if user.bot:
            await interaction.response.send_message("We marrying clankers now? :wilted_rose: :sob: :v:")
            return

        proposee_id = interaction.user.id
        proposed_id = user.id
        marriage_candidates = [proposee_id, proposed_id]
        marriage_candidates.sort()

        existing_marriage = await fetch_one("SELECT 1 FROM marriages WHERE spouse1_id = ? AND spouse2_id = ?", (marriage_candidates[0], marriage_candidates[1]))

        if existing_marriage:
            await interaction.response.send_message(f"Silly! You're already happily (hopefully) married with **{user.display_name}**!")
            return

        existing_spouse = await fetch_one(
            "SELECT 1 FROM marriages WHERE spouse1_id IN (?, ?) OR spouse2_id IN (?, ?)",
            (
                marriage_candidates[0],
                marriage_candidates[1],
                marriage_candidates[0],
                marriage_candidates[1],
            ),
        )

        if existing_spouse:
            await interaction.response.send_message("One of you is already married. Divorce first before proposing again.")
            return

        await interaction.response.send_message(view=MarriageConfirmView(interaction, user)) 

    @app_commands.command(name="divorce", description="Divorce a user you have married.")
    @app_commands.guild_only()
    @app_commands.describe(user="Who to divorce")
    async def divorce(self, interaction: discord.Interaction, user: discord.User):
        if user.id == interaction.user.id:
            await interaction.response.send_message("You can't divorce yourself... </3")
            return

        divorcer_id = interaction.user.id
        divorcee_id = user.id
        divorce_user_ids = [divorcer_id, divorcee_id]
        divorce_user_ids.sort()

        existing_marriage = await fetch_one("SELECT 1 FROM marriages WHERE spouse1_id = ? AND spouse2_id = ?", (divorce_user_ids[0], divorce_user_ids[1]))

        if not existing_marriage:
            await interaction.response.send_message(f"You're not married with **{user.display_name}**!")
            return

        await interaction.response.send_message(f"</3 {user.mention}, I'm sorry to say, but {interaction.user.mention} has decided to divorce you...")
        await execute_query("DELETE FROM marriages WHERE spouse1_id = ? AND spouse2_id = ?", (divorce_user_ids[0], divorce_user_ids[1]))
    
    @app_commands.command(name="adopt", description="Adopt a user as your child.")
    @app_commands.guild_only()
    @app_commands.describe(user="Who to adopt")
    async def adopt(self, interaction: discord.Interaction, user: discord.User):
        if user.id == interaction.user.id:
            await interaction.response.send_message("You can't adopt yourself... </3")
            return

        if user.bot:
            await interaction.response.send_message("We adopting clankers now? :wilted_rose: :sob: :v:")
            return
        
        soon_to_be_parent_id = interaction.user.id
        soon_to_be_child_id = user.id

        existing_offspring = await fetch_one("SELECT 1 FROM children WHERE child_id = ? AND parent_id = ?", (soon_to_be_child_id, soon_to_be_parent_id))

        if existing_offspring:
            await interaction.response.send_message(f"Nuh uh! You already have adopted **{user.display_name}** as your child!")
            return

        existing_parent = await fetch_one(
            "SELECT 1 FROM children WHERE child_id = ?",
            (soon_to_be_child_id,),
        )

        if existing_parent:
            await interaction.response.send_message(f"**{user.display_name}** already has a parent!")
            return

        await interaction.response.send_message(view=AdoptionConfirmView(interaction, user)) 
    
    @app_commands.command(name="disown", description="Disown a child of yours.")
    @app_commands.guild_only()
    @app_commands.describe(user="Who to disown")
    async def disown(self, interaction: discord.Interaction, user: discord.User):
        if user.id == interaction.user.id:
            await interaction.response.send_message("You can't disown yourself... </3")
            return

        if user.bot:
            await interaction.response.send_message("Ain't no clanker is your child cro... :broken_heart: :sob: :v: :wilted_rose:")
            return
        
        disowner_id = interaction.user.id
        disowned_id = user.id

        relationship = await fetch_one("SELECT 1 FROM children WHERE child_id = ? AND parent_id = ?", (disowned_id, disowner_id))

        if not relationship:
            await interaction.response.send_message(f"The user **{user.display_name}** is not your child!")
            return
        
        await interaction.response.send_message(f"</3 {user.mention}, I'm sorry to say, but {interaction.user.mention} has decided to disown you...")
        await execute_query("DELETE FROM children WHERE child_id = ? AND parent_id = ?", (disowned_id, disowner_id))

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FamilyCommands(bot))
