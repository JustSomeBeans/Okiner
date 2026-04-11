from __future__ import annotations

# =============================================================================
# views.py — Discord UI components (discord.ui.View subclasses)
# -----------------------------------------------------------------------------
# Imported by:  cogs/rp_commands.py → ActionTextConfirmView
# Imports from: database.py → add_rp_entry  (called on confirm button press)
#               discord    → discord.ui.View, discord.ui.Button,
#                            discord.Interaction, discord.ButtonStyle
# =============================================================================

import discord

from database import add_rp_entry


class ActionTextConfirmView(discord.ui.View):
    """Confirmation prompt shown when an action text is missing {user} or {target} tags."""

    def __init__(self, user_id: int, guild_id: int, rp_type: str, action_text: str) -> None:
        super().__init__(timeout=60)
        self.user_id = user_id
        self.guild_id = guild_id
        self.rp_type = rp_type
        self.action_text = action_text

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who used the command can confirm.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Yes, Add It", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await add_rp_entry(self.user_id, self.guild_id, self.rp_type, action_text=self.action_text)
        await interaction.response.edit_message(
            content=f"✅ Added action text to `{self.rp_type}` despite missing tags.",
            view=None,
        )

    @discord.ui.button(label="No, Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="❌ Action text addition cancelled.", view=None)