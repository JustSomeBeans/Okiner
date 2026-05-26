from __future__ import annotations

from typing import TYPE_CHECKING

# =============================================================================
# views.py — Discord UI components (discord.ui.View subclasses)
# -----------------------------------------------------------------------------
# Imported by:  cogs/rp_commands.py → ActionTextConfirmView
# Imports from: database.py         → add_rp_entry
#               discord             → discord.ui.View, discord.ui.Button,
#                                     discord.Interaction, discord.ButtonStyle
# =============================================================================

import discord
import logging
import time

from config import EVERYONE_TARGET, SELF_CASE, STANDARD_CASE
from database import add_rp_entry, execute_query
from utils import PlaceholderTarget

if TYPE_CHECKING:
    from cogs.rp_commands import RPCommands


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
            except discord.HTTPException:
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


class RPBackView(discord.ui.View):
    """Button that lets the original RP target send the same interaction back."""

    def __init__(
        self,
        cog: "RPCommands",
        rp_type: str,
        original_actor_id: int,
        target_id: int | None,
        guild_id: int,
    ) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.rp_type = rp_type
        self.original_actor_id = original_actor_id
        self.target_id = target_id
        self.guild_id = guild_id
        self.back.label = f"{rp_type} back"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.target_id is None:
            return True

        if interaction.user.id != self.target_id:
            await interaction.response.send_message(
                f"Only <@{self.target_id}> can use this button.",
                ephemeral=True,
            )
            return False

        return True

    async def on_timeout(self) -> None:
        """Disable the button and update the message when the response window expires."""
        for item in self.children:
            item.disabled = True

        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    @discord.ui.button(label="RP back", style=discord.ButtonStyle.blurple)
    async def back(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Reverse the original RP interaction, with everyone-target replies staying reusable until timeout."""
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "This button can only be used in a server.",
                ephemeral=True,
            )
            return

        member = guild.get_member(self.original_actor_id)
        if member is None:
            await interaction.response.send_message(
                "Couldn't find the original user.",
                ephemeral=True,
            )
            return

        target_info = PlaceholderTarget(member.mention, member.display_name)
        case_type = (
            SELF_CASE
            if interaction.user.id == self.original_actor_id
            else STANDARD_CASE
        )

        await self.cog._execute_rp(
            interaction,
            self.rp_type,
            target_info,
            case_type,
        )

        if self.target_id is not None:
            button.disabled = True
            self.stop()

        if self.target_id is not None and interaction.message is not None:
            try:
                await interaction.message.edit(view=self)
            except discord.HTTPException:
                pass


class MarriageContainer(discord.ui.Container):    
    def __init__(self, interaction: discord.Interaction, target: discord.User, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.original_interaction = interaction

        text = discord.ui.TextDisplay(f"Hey {target.mention}! {interaction.user.mention} wants to marry you!")
        action_row = discord.ui.ActionRow()
        accept_button = discord.ui.Button(label="Accept", style=discord.ButtonStyle.green, emoji="💍")
        reject_button = discord.ui.Button(label="Reject", style=discord.ButtonStyle.red, emoji="👎")
        action_row.add_item(accept_button)
        action_row.add_item(reject_button)
        accept_button.callback = self.accept_callback
        reject_button.callback = self.reject_callback

        self.add_item(text)
        self.add_item(action_row)

    async def accept_callback(self, interaction: discord.Interaction):
        proposed_id = interaction.user.id
        proposee_id = self.original_interaction.user.id
        marriage_candidates = [proposed_id, proposee_id]
        marriage_candidates.sort()

        try:
            await execute_query(
                "INSERT INTO marriages (spouse1_id, spouse2_id, marriage_date) VALUES (?, ?, ?)",
                (marriage_candidates[0], marriage_candidates[1], time.time())
            )
        except Exception:
            logging.exception("Failed to create marriage record")
            await interaction.response.send_message(
                "I couldn't save the marriage right now because of a database issue. Please try again later.",
                ephemeral=True,
            )
            return
        await self.end()
        await interaction.response.edit_message(content=None, view=self.view)
        await interaction.followup.send(f"<3 <3 Congratulations, {interaction.user.mention} and {self.original_interaction.user.mention}! You both are now happily married together! You may now kiss!")
        self.view.stop()

    async def reject_callback(self, interaction: discord.Interaction):
        await self.end()
        await interaction.response.edit_message(content=None, view=self.view)
        await interaction.followup.send(f"Awh... sorry {self.original_interaction.user.mention}, but {interaction.user.mention} rejected your proposal...")
        self.view.stop()

    async def end(self):
        for child in self.children:
            if isinstance(child, discord.ui.ActionRow):
                for item in child.children:
                    if hasattr(item, 'disabled'):
                        item.disabled = True

class MarriageConfirmView(discord.ui.LayoutView):
    """Marriage confirmation view when a user requests for marriage (so they don't get raped)"""
    def __init__(self, interaction: discord.Interaction, target: discord.User) -> None:
        super().__init__()
        self.target = target
        self.interaction = interaction

        self.container = container = MarriageContainer(interaction=interaction, target=target, accent_color=0x7289da)
        self.add_item(container)
    
    async def on_timeout(self) -> None:
        for child in self.container.children:
            if isinstance(child, discord.ui.ActionRow):
                for item in child.children:
                    if hasattr(item, 'disabled'):
                        item.disabled = True
        
        await self.interaction.edit_original_response(content=None, view=self)
        await self.interaction.followup.send(f"The proposal is automatically rejected because {self.target.mention} didn't respond in time! How unfortunate....")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.target.id:
            await interaction.response.send_message(
                "Only the person who is being proposed to can confirm.",
                ephemeral=True,
            )
            return False
        return True

class AdoptionConfirmView(discord.ui.LayoutView):
    """Adoption confirmation view when a user wants to adopt another one."""
    def __init__(self, interaction: discord.Interaction, target: discord.User) -> None:
        super().__init__()
        self.target = target
        self.interaction = interaction

        self.container = container = AdoptContainer(interaction=interaction, target=target, accent_color=0x7289da)
        self.add_item(container)
    
    async def on_timeout(self) -> None:
        for child in self.container.children:
            if isinstance(child, discord.ui.ActionRow):
                for item in child.children:
                    if hasattr(item, 'disabled'):
                        item.disabled = True
        
        await self.interaction.edit_original_response(content=None, view=self)
        await self.interaction.followup.send(f"The adoption is automatically rejected because {self.target.mention} didn't respond in time! How unfortunate....")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.target.id:
            await interaction.response.send_message(
                "Only the person who is being requested to can confirm.",
                ephemeral=True,
            )
            return False
        return True

class AdoptContainer(discord.ui.Container):    
    def __init__(self, interaction: discord.Interaction, target: discord.User, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.original_interaction = interaction

        text = discord.ui.TextDisplay(f"Hey {target.mention}! {interaction.user.mention} wants to adopt you!")
        action_row = discord.ui.ActionRow()
        accept_button = discord.ui.Button(label="Accept", style=discord.ButtonStyle.green, emoji="🍼")
        reject_button = discord.ui.Button(label="Reject", style=discord.ButtonStyle.red, emoji="👎")
        action_row.add_item(accept_button)
        action_row.add_item(reject_button)
        accept_button.callback = self.accept_callback
        reject_button.callback = self.reject_callback

        self.add_item(text)
        self.add_item(action_row)

    async def accept_callback(self, interaction: discord.Interaction):
        child_id = interaction.user.id
        parent_id = self.original_interaction.user.id

        try:
            await execute_query(
                "INSERT INTO children (child_id, parent_id, adoption_date) VALUES (?, ?, ?)",
                (child_id, parent_id, time.time())
            )
        except Exception:
            logging.exception("Failed to create child record")
            await interaction.response.send_message(
                "I couldn't save the adoption right now because of a database issue. Please try again later.",
                ephemeral=True,
            )
            return
        await self.end()
        await interaction.response.edit_message(content=None, view=self.view)
        await interaction.followup.send(f"<3 <3 Congratulations, {interaction.user.mention}! You now have {self.original_interaction.user.mention} as your new parent!")
        self.view.stop()

    async def reject_callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"Awh... sorry {self.original_interaction.user.mention}, but {interaction.user.mention} rejected your adoption request...")
    
    async def end(self):
        for child in self.children:
            if isinstance(child, discord.ui.ActionRow):
                for item in child.children:
                    if hasattr(item, 'disabled'):
                        item.disabled = True
