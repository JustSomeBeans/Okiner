from __future__ import annotations

# =============================================================================
# views.py — Discord UI components (discord.ui.View subclasses)
# -----------------------------------------------------------------------------
# Imported by:  cogs/rp_commands.py → ActionTextConfirmView
# Imports from: database.py         → add_rp_entry
#               discord             → discord.ui.View, discord.ui.Button,
#                                     discord.Interaction, discord.ButtonStyle
# =============================================================================

import discord

from database import add_rp_entry


class ActionTextConfirmView(discord.ui.View):
    """Confirmation prompt shown when an action text is missing expected tags."""

    def __init__(
        self,
        user_id: int,
        guild_id: int,
        rp_type: str,
        action_text: str,
        *,
        case_type: str = "standard",
    ) -> None:
        super().__init__(timeout=60)
        self.user_id = user_id
        self.guild_id = guild_id
        self.rp_type = rp_type
        self.action_text = action_text
        self.case_type = case_type

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who used the command can confirm.",
                ephemeral=True,
            )
            return False
        return True
    
    async def on_timeout(self) -> None:
        """Disable the buttons and update the message when the confirmation window expires."""
        for item in self.children:
            item.disabled = True
        # message is the attribute discord.py sets automatically when the view
        #is attached via send_message(..., view=self)
        if self.message is not None:
            try:
                await self.message.edit(
                    content="Confirmation timed out. Run the command again if you still want to add it.",
                    view=self,
                )
            except discord.HTTPCException:
                pass # Most likely message deleted or channel gone - really not worth crashing over.

    @discord.ui.button(label="Yes, Add It", style=discord.ButtonStyle.green)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Save the action text anyway after the user confirms the warning."""
        await add_rp_entry(
            self.user_id,
            self.guild_id,
            self.rp_type,
            case_type=self.case_type,
            action_text=self.action_text,
        )
        await interaction.response.edit_message(
            content=f"Added {self.case_type} action text to `{self.rp_type}` despite missing tags.",
            view=None,
        )

    @discord.ui.button(label="No, Cancel", style=discord.ButtonStyle.red)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Close the prompt without saving anything."""
        await interaction.response.edit_message(
            content="Action text addition cancelled.", view=None
        )
