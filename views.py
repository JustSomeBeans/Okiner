from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, Callable

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
import sqlite3
import time

from checks import has_manage_messages
from config import EVERYONE_TARGET, MAX_URL_LENGTH, SELF_CASE, STANDARD_CASE
from database import add_child, add_marriage, add_rp_entry, execute_query, fetch_column, remove_rp_entry, update_rp_entry
from utils import PlaceholderTarget, is_imgur_page_url, is_valid_image_url, normalize_image_url

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
        on_confirm: Callable[[discord.Interaction], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(timeout=60)
        self.message: discord.Message | None = None
        self.user_id = user_id
        self.guild_id = guild_id
        self.rp_type = rp_type
        self.action_text = action_text
        self.case_type = case_type
        self.on_confirm = on_confirm

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
            if hasattr(item, "disabled"):
                item.disabled = True
        # message is the attribute discord.py sets automatically when the view
        #is attached via send_message(..., view=self)
        if self.message is not None:
            try:
                await self.message.edit(
                    content="Confirmation timed out. Run the command again if you still want to add it.",
                    view=self,
                )
            except (discord.NotFound, discord.HTTPException):
                pass # Most likely message deleted or channel gone - really not worth crashing over.

    @discord.ui.button(label="Yes, Add It", style=discord.ButtonStyle.green)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Save the action text anyway after the user confirms the warning."""
        self.stop()
        if self.on_confirm is not None:
            await self.on_confirm(interaction)
        else:
            try:
                added = await add_rp_entry(
                    self.user_id,
                    self.guild_id,
                    self.rp_type,
                    case_type=self.case_type,
                    action_text=self.action_text,
                )
                if not added:
                    await interaction.response.edit_message(
                        content="That action text is already saved for this RP type.",
                        view=None,
                    )
                    return
                await interaction.response.edit_message(
                    content=f"Added {self.case_type} action text to `{self.rp_type}` despite missing tags.",
                    view=None,
                )
            except sqlite3.IntegrityError:
                await interaction.response.edit_message(
                    content="That RP type no longer exists.",
                    view=None,
                )

    @discord.ui.button(label="No, Cancel", style=discord.ButtonStyle.red)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        """Close the prompt without saving anything."""
        self.stop()
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
        self.message: discord.Message | None = None
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
            if hasattr(item, "disabled"):
                item.disabled = True

        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
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
            await add_marriage(marriage_candidates[0], marriage_candidates[1], int(time.time()))
        except sqlite3.IntegrityError:
            await interaction.response.send_message(
                "You or your partner are already married, or a conflicting relationship record exists.",
                ephemeral=True,
            )
            return
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
        
        try:
            await self.interaction.edit_original_response(content=None, view=self)
        except (discord.NotFound, discord.HTTPException):
            pass
        try:
            await self.interaction.followup.send(f"The proposal is automatically rejected because {self.target.mention} didn't respond in time! How unfortunate....")
        except (discord.NotFound, discord.HTTPException):
            pass

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
        
        try:
            await self.interaction.edit_original_response(content=None, view=self)
        except (discord.NotFound, discord.HTTPException):
            pass
        try:
            await self.interaction.followup.send(f"The adoption is automatically rejected because {self.target.mention} didn't respond in time! How unfortunate....")
        except (discord.NotFound, discord.HTTPException):
            pass

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
            await add_child(child_id, parent_id, int(time.time()))
        except sqlite3.IntegrityError:
            await interaction.response.send_message(
                "You already have a parent or this adoption relationship already exists.",
                ephemeral=True,
            )
            return
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
        await self.end()
        await interaction.response.edit_message(content=None, view=self.view)
        await interaction.followup.send(f"Awh... sorry {self.original_interaction.user.mention}, but {interaction.user.mention} rejected your adoption request...")
        self.view.stop()
    
    async def end(self):
        for child in self.children:
            if isinstance(child, discord.ui.ActionRow):
                for item in child.children:
                    if hasattr(item, 'disabled'):
                        item.disabled = True


class AddRPOptionsView(discord.ui.View):
    """View to select case configuration mode for /add_rp."""

    def __init__(self, user_id: int, rp_type: str, image_url: str, cog: "RPCommands") -> None:
        super().__init__(timeout=300)
        self.message: discord.Message | None = None
        self.user_id = user_id
        self.rp_type = rp_type
        self.image_url = image_url
        self.cog = cog
        self.mode = "standard"  # "standard", "self", "null", "standard_self_null"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who ran the command can configure options.",
                ephemeral=True,
            )
            return False
        if not has_manage_messages(interaction):
            await interaction.response.send_message(
                "You no longer have permission to manage RP entries.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(content="Configuration timed out.", view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

    @discord.ui.button(label="Mode: Standard Only", style=discord.ButtonStyle.primary, custom_id="mode_std")
    async def select_mode(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.mode == "standard":
            self.mode = "self"
            button.label = "Mode: Standard + Selfcase"
            button.style = discord.ButtonStyle.success
        elif self.mode == "self":
            self.mode = "null"
            button.label = "Mode: Standard + Nullcase"
            button.style = discord.ButtonStyle.blurple
        elif self.mode == "null":
            self.mode = "standard_self_null"
            button.label = "Mode: Standard + Self + Null"
            button.style = discord.ButtonStyle.danger
        else:
            self.mode = "standard"
            button.label = "Mode: Standard Only"
            button.style = discord.ButtonStyle.primary
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Continue to Inputs", style=discord.ButtonStyle.green, custom_id="continue")
    async def continue_setup(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        modal = AddRPModal(self.rp_type, self.image_url, self.mode, self.cog)
        await interaction.response.send_modal(modal)
        self.stop()


class AddRPModal(discord.ui.Modal):
    """Modal to collect RP entries for /add_rp."""

    def __init__(self, rp_type: str, image_url: str, mode: str, cog: "RPCommands") -> None:
        title_suffix = (
            " (Standard + Selfcase)" if mode == "self"
            else " (Standard + Nullcase)" if mode == "null"
            else " (Standard + Self + Null)" if mode == "standard_self_null"
            else " (Standard Only)"
        )
        super().__init__(title=f"Add RP: {rp_type}{title_suffix}")
        self.rp_type = rp_type
        self.image_url = image_url
        self.mode = mode
        self.cog = cog

        self.std_text_input = discord.ui.TextInput(
            label="Standard Text (Required)",
            placeholder="Embed text template (supports {user}, {target})",
            style=discord.TextStyle.paragraph,
            max_length=1500,
            required=True,
        )
        self.std_action_input = discord.ui.TextInput(
            label="Standard Action Text (Required)",
            placeholder="Header action (e.g. {user} hugs {target})",
            max_length=1500,
            required=True,
        )
        self.add_item(self.std_text_input)
        self.add_item(self.std_action_input)

        if mode in {"self", "standard_self_null"}:
            self.self_text_input = discord.ui.TextInput(
                label="Selfcase Text (Optional)",
                placeholder="Text template when targeting oneself",
                style=discord.TextStyle.paragraph,
                max_length=1500,
                required=False,
            )
            self.add_item(self.self_text_input)

        if mode in {"null", "standard_self_null"}:
            self.null_text_input = discord.ui.TextInput(
                label="Nullcase Text (Optional)",
                placeholder="Text template when no target is given",
                style=discord.TextStyle.paragraph,
                max_length=1500,
                required=False,
            )
            self.add_item(self.null_text_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not has_manage_messages(interaction):
            await interaction.response.send_message(
                "You no longer have permission to manage RP entries.",
                ephemeral=True,
            )
            return
        self_text = getattr(self, "self_text_input", None)
        null_text = getattr(self, "null_text_input", None)
        await self.cog._handle_add_rp_submission(
            interaction,
            self.rp_type,
            self.image_url,
            self.std_text_input.value,
            self.std_action_input.value,
            self.mode,
            self_text.value if self_text else None,
            null_text.value if null_text else None,
        )


class EditRPOptionsView(discord.ui.View):
    """View to select data pool when editing an existing RP type with /edit_rp."""

    def __init__(self, user_id: int, rp_type: str, cog: "RPCommands") -> None:
        super().__init__(timeout=300)
        self.message: discord.Message | None = None
        self.user_id = user_id
        self.rp_type = rp_type
        self.cog = cog

        select = discord.ui.Select(
            placeholder="Select data pool to add to...",
            options=[
                discord.SelectOption(label="Standard Image URL", value="std_img", description="Add an image to standard pool"),
                discord.SelectOption(label="Standard Text", value="std_text", description="Add embed text template"),
                discord.SelectOption(label="Standard Action Text", value="std_action", description="Add action text header"),
                discord.SelectOption(label="Selfcase Text", value="self_text", description="Add selfcase embed text"),
                discord.SelectOption(label="Selfcase Action Text", value="self_action", description="Add selfcase action text"),
                discord.SelectOption(label="Nullcase Text", value="null_text", description="Add nullcase embed text"),
                discord.SelectOption(label="Nullcase Action Text", value="null_action", description="Add nullcase action text"),
            ],
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who ran the command can use this menu.",
                ephemeral=True,
            )
            return False
        if not has_manage_messages(interaction):
            await interaction.response.send_message(
                "You no longer have permission to manage RP entries.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

    async def select_callback(self, interaction: discord.Interaction) -> None:
        val = interaction.data["values"][0]
        modal = EditRPModal(self.rp_type, val, self.cog)
        await interaction.response.send_modal(modal)
        self.stop()


class EditRPModal(discord.ui.Modal):
    """Modal to enter new entry value for /edit_rp."""

    def __init__(self, rp_type: str, pool_type: str, cog: "RPCommands") -> None:
        titles = {
            "std_img": "Add Standard Image",
            "std_text": "Add Standard Text",
            "std_action": "Add Standard Action Text",
            "self_text": "Add Selfcase Text",
            "self_action": "Add Selfcase Action Text",
            "null_text": "Add Nullcase Text",
            "null_action": "Add Nullcase Action Text",
        }
        super().__init__(title=f"Edit RP ({rp_type}): {titles.get(pool_type, pool_type)}")
        self.rp_type = rp_type
        self.pool_type = pool_type
        self.cog = cog

        label = "Image URL (http/https)" if pool_type == "std_img" else "Text Template"
        placeholder = "Direct image link (i.imgur.com/...)" if pool_type == "std_img" else "Enter text template..."
        style = discord.TextStyle.short if pool_type == "std_img" else discord.TextStyle.paragraph

        self.value_input = discord.ui.TextInput(
            label=label,
            placeholder=placeholder,
            style=style,
            max_length=1500,
            required=True,
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not has_manage_messages(interaction):
            await interaction.response.send_message(
                "You no longer have permission to manage RP entries.",
                ephemeral=True,
            )
            return
        await self.cog._handle_edit_rp_submission(
            interaction,
            self.rp_type,
            self.pool_type,
            self.value_input.value,
        )


class ManageRPView(discord.ui.View):
    """Step 1 & 2 of /manage_rp: selecting RP type and data pool."""

    def __init__(self, user_id: int, guild_id: int, rp_types: list[str], cog: "RPCommands") -> None:
        super().__init__(timeout=300)
        self.message: discord.Message | None = None
        self.user_id = user_id
        self.guild_id = guild_id
        self.rp_types = rp_types
        self.cog = cog
        self.selected_type: str | None = None
        self.selected_pool: str | None = None

        self.type_select = discord.ui.Select(
            placeholder="Select RP type to manage...",
            options=[discord.SelectOption(label=t[:100], value=t) for t in rp_types[:25]],
        )
        self.type_select.callback = self.type_select_callback
        self.add_item(self.type_select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who ran the command can use this menu.",
                ephemeral=True,
            )
            return False
        if not has_manage_messages(interaction):
            await interaction.response.send_message(
                "You no longer have permission to manage RP entries.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

    async def type_select_callback(self, interaction: discord.Interaction) -> None:
        self.selected_type = interaction.data["values"][0]
        self.clear_items()
        pool_select = discord.ui.Select(
            placeholder=f"Managing `{self.selected_type}`. Select data category...",
            options=[
                discord.SelectOption(label="Standard Images", value="std_img", description="Manage image URLs"),
                discord.SelectOption(label="Standard Texts", value="std_text", description="Manage embed text templates"),
                discord.SelectOption(label="Standard Action Texts", value="std_action", description="Manage action text templates"),
                discord.SelectOption(label="Selfcase Texts", value="self_text", description="Manage selfcase embed texts"),
                discord.SelectOption(label="Selfcase Action Texts", value="self_action", description="Manage selfcase action texts"),
                discord.SelectOption(label="Nullcase Texts", value="null_text", description="Manage nullcase embed texts"),
                discord.SelectOption(label="Nullcase Action Texts", value="null_action", description="Manage nullcase action texts"),
                discord.SelectOption(label="🗑️ Remove RP Type", value="remove_type", description="Delete entire RP type and all entries"),
            ],
        )
        pool_select.callback = self.pool_select_callback
        self.add_item(pool_select)

        back_button = discord.ui.Button(label="« Back to Types", style=discord.ButtonStyle.secondary)
        back_button.callback = self.back_to_types_callback
        self.add_item(back_button)

        await interaction.response.edit_message(content=f"Managing RP type: **{self.selected_type}**", view=self)

    async def back_to_types_callback(self, interaction: discord.Interaction) -> None:
        self.clear_items()
        self.selected_type = None
        self.type_select = discord.ui.Select(
            placeholder="Select RP type to manage...",
            options=[discord.SelectOption(label=t[:100], value=t) for t in self.rp_types[:25]],
        )
        self.type_select.callback = self.type_select_callback
        self.add_item(self.type_select)
        await interaction.response.edit_message(content="Select an RP type to manage:", view=self)

    async def pool_select_callback(self, interaction: discord.Interaction) -> None:
        self.selected_pool = interaction.data["values"][0]
        if self.selected_pool == "remove_type":
            if not has_manage_messages(interaction):
                await interaction.response.send_message(
                    "You no longer have permission to manage RP entries.",
                    ephemeral=True,
                )
                return
            try:
                await execute_query(
                    "DELETE FROM rp_types WHERE guild_id = ? AND type = ?",
                    (self.guild_id, self.selected_type),
                )
                await interaction.response.edit_message(
                    content=f"Removed RP type `{self.selected_type}` and all associated entries.",
                    view=None,
                )
                self.stop()
            except Exception:
                logging.exception("Failed to remove RP type")
                await interaction.response.send_message(
                    "Failed to remove RP type due to a database error.", ephemeral=True
                )
            return

        case_map = {
            "std_img": ("standard", "url"),
            "std_text": ("standard", "texts"),
            "std_action": ("standard", "action_texts"),
            "self_text": ("selfcase", "texts"),
            "self_action": ("selfcase", "action_texts"),
            "null_text": ("nullcase", "texts"),
            "null_action": ("nullcase", "action_texts"),
        }
        case_mapping = case_map.get(self.selected_pool)
        if case_mapping is None:
            await interaction.response.send_message(
                "That option isn't available anymore. Please run /manage_rp again.",
                ephemeral=True,
            )
            return
        case_type, column = case_mapping
        
        async with interaction.client.db_pool.acquire() as conn:
            result = await conn.execute(
                f"SELECT {column} FROM roleplay_entries WHERE guild_id = ? AND type = ? AND case_type = ? AND {column} IS NOT NULL ORDER BY {column}",
                (self.guild_id, self.selected_type, case_type),
            )
            rows = await result.fetchall()
            entries = [row[0] for row in rows]

        if not entries:
            await interaction.response.send_message(
                f"No entries found under `{self.selected_pool}` for `{self.selected_type}`.",
                ephemeral=True,
            )
            return

        entries_view = ManageRPEntriesView(
            user_id=self.user_id,
            guild_id=self.guild_id,
            rp_type=self.selected_type,
            pool=self.selected_pool,
            case_type=case_type,
            column=column,
            entries=entries,
            cog=self.cog,
            parent_view=self,
        )
        entries_view.message = interaction.message
        await entries_view._show(interaction)
        self.stop()


class ManageRPEntriesView(discord.ui.View):
    """Step 3 of /manage_rp: paginated browser with Delete, Edit, and Breadcrumb Back."""

    def __init__(
        self,
        user_id: int,
        guild_id: int,
        rp_type: str,
        pool: str,
        case_type: str,
        column: str,
        entries: list[str],
        cog: "RPCommands",
        parent_view: ManageRPView,
    ) -> None:
        super().__init__(timeout=300)
        self.message: discord.Message | None = None
        self.user_id = user_id
        self.guild_id = guild_id
        self.rp_type = rp_type
        self.pool = pool
        self.case_type = case_type
        self.column = column
        self.entries = entries
        self.cog = cog
        self.parent_view = parent_view
        self.page = 0

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Only the person who ran the command can navigate this view.",
                ephemeral=True,
            )
            return False
        if not has_manage_messages(interaction):
            await interaction.response.send_message(
                "You no longer have permission to manage RP entries.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException):
                pass

    def render_content(self) -> str:
        if not self.entries:
            return f"Managing `{self.rp_type}` ({self.pool}): No entries remaining."
        entry = self.entries[self.page]
        return f"Managing `{self.rp_type}` ({self.pool}) — Entry {self.page + 1} of {len(self.entries)}:\n```\n{entry}\n```"

    def render_kwargs(self) -> dict:
        if not self.entries or self.column != "url":
            return {"content": self.render_content(), "embed": None}
        entry = self.entries[self.page]
        header = f"Managing `{self.rp_type}` ({self.pool}) — Entry {self.page + 1} of {len(self.entries)}:"
        embed = discord.Embed(description=entry.replace("`", "'")[:4000], color=discord.Color.blurple())
        embed.set_image(url=entry)
        return {"content": header, "embed": embed}

    async def _show(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.response.edit_message(**self.render_kwargs(), view=self)
        except discord.HTTPException:
            if interaction.response.is_done() is False:
                logging.warning("HTTPException in ManageRPEntriesView._show; falling back to text-only")
                await interaction.response.edit_message(content=self.render_content(), embed=None, view=self)
            else:
                raise

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary, custom_id="prev")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.page > 0:
            self.page -= 1
        await self._show(interaction)

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, custom_id="delete")
    async def delete_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not self.entries:
            await interaction.response.send_message("No entry to delete.", ephemeral=True)
            return
        entry = self.entries[self.page]
        try:
            await remove_rp_entry(self.guild_id, self.rp_type, self.case_type, self.column, entry)
            self.entries.pop(self.page)
            if self.page >= len(self.entries) and self.page > 0:
                self.page -= 1
            if not self.entries:
                await interaction.response.edit_message(
                    content=f"Deleted entry. All entries for `{self.pool}` under `{self.rp_type}` have been removed.",
                    embed=None,
                    view=None,
                )
                self.stop()
                return
            await self._show(interaction)
        except Exception:
            logging.exception("Failed to delete entry")
            await interaction.response.send_message("Failed to delete entry due to database error.", ephemeral=True)

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.primary, custom_id="edit")
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not self.entries:
            await interaction.response.send_message("No entry to edit.", ephemeral=True)
            return
        entry = self.entries[self.page]
        modal = EditEntryModal(self, entry)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, custom_id="next")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.page < len(self.entries) - 1:
            self.page += 1
        await self._show(interaction)

    @discord.ui.button(label="« Back", style=discord.ButtonStyle.secondary, custom_id="back")
    async def back_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        types = await fetch_column(
            "SELECT type FROM rp_types WHERE guild_id = ? ORDER BY type COLLATE NOCASE",
            (self.guild_id,),
        )
        new_view = ManageRPView(self.user_id, self.guild_id, types, self.cog)
        new_view.selected_type = self.rp_type
        new_view.clear_items()
        pool_select = discord.ui.Select(
            placeholder=f"Managing `{self.rp_type}`. Select data category...",
            options=[
                discord.SelectOption(label="Standard Images", value="std_img", description="Manage image URLs"),
                discord.SelectOption(label="Standard Texts", value="std_text", description="Manage embed text templates"),
                discord.SelectOption(label="Standard Action Texts", value="std_action", description="Manage action text templates"),
                discord.SelectOption(label="Selfcase Texts", value="self_text", description="Manage selfcase embed texts"),
                discord.SelectOption(label="Selfcase Action Texts", value="self_action", description="Manage selfcase action texts"),
                discord.SelectOption(label="Nullcase Texts", value="null_text", description="Manage nullcase embed texts"),
                discord.SelectOption(label="Nullcase Action Texts", value="null_action", description="Manage nullcase action texts"),
                discord.SelectOption(label="🗑️ Remove RP Type", value="remove_type", description="Delete entire RP type and all entries"),
            ],
        )
        pool_select.callback = new_view.pool_select_callback
        new_view.add_item(pool_select)
        back_btn = discord.ui.Button(label="« Back to Types", style=discord.ButtonStyle.secondary)
        back_btn.callback = new_view.back_to_types_callback
        new_view.add_item(back_btn)

        new_view.message = interaction.message
        await interaction.response.edit_message(content=f"Managing RP type: **{self.rp_type}**", embed=None, view=new_view)
        self.stop()


class EditEntryModal(discord.ui.Modal):
    """Modal to edit an existing entry in place."""

    def __init__(self, browser_view: ManageRPEntriesView, old_entry: str) -> None:
        super().__init__(title="Edit RP Entry")
        self.browser_view = browser_view
        self.old_entry = old_entry

        self.input_field = discord.ui.TextInput(
            label="Updated Value",
            default=old_entry[:100],
            style=discord.TextStyle.paragraph if browser_view.column != "url" else discord.TextStyle.short,
            max_length=1500,
            required=True,
        )
        self.add_item(self.input_field)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not has_manage_messages(interaction):
            await interaction.response.send_message(
                "You no longer have permission to manage RP entries.",
                ephemeral=True,
            )
            return
        new_value = self.input_field.value.strip()
        if not new_value:
            await interaction.response.send_message("Value cannot be blank.", ephemeral=True)
            return
        
        if self.browser_view.column == "url":
            new_value = normalize_image_url(new_value)
            if is_imgur_page_url(new_value):
                await interaction.response.send_message(
                    "Please provide the direct image link (`i.imgur.com`).", ephemeral=True
                )
                return
            if not is_valid_image_url(new_value):
                await interaction.response.send_message("Invalid image URL.", ephemeral=True)
                return
            if len(new_value) > MAX_URL_LENGTH:
                await interaction.response.send_message("That URL is longer than I want to store safely.", ephemeral=True)
                return

        try:
            await update_rp_entry(
                self.browser_view.guild_id,
                self.browser_view.rp_type,
                self.browser_view.case_type,
                self.browser_view.column,
                self.old_entry,
                new_value,
            )
            idx = self.browser_view.entries.index(self.old_entry)
            self.browser_view.entries[idx] = new_value
            await self.browser_view._show(interaction)
        except sqlite3.IntegrityError:
            await interaction.response.send_message("That value already exists for this RP type.", ephemeral=True)
        except Exception:
            logging.exception("Failed to update RP entry")
            await interaction.response.send_message("Failed to update entry due to database error.", ephemeral=True)
