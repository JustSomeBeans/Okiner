import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from discord import app_commands

import checks
from views import (
    AddRPOptionsView,
    EditRPOptionsView,
    ManageRPView,
    ManageRPEntriesView,
    AddRPModal,
    EditRPModal,
    EditEntryModal,
)


class TestAuthorization(unittest.IsolatedAsyncioTestCase):

    def _get_moderator_only_predicate(self):
        deco = checks.moderator_only()
        async def dummy():
            pass
        wrapped = deco(dummy)
        return wrapped.__discord_app_commands_checks__[0]

    async def test_moderator_only_predicate(self):
        pred = self.get_predicate = self._get_moderator_only_predicate()

        # 1. guild is None -> raises NoPrivateMessage
        interaction_dm = MagicMock(spec=discord.Interaction)
        interaction_dm.guild = None
        with self.assertRaises(app_commands.NoPrivateMessage):
            await pred(interaction_dm)

        # 2. manage_messages = True -> returns True
        interaction_mm = MagicMock(spec=discord.Interaction)
        interaction_mm.guild = MagicMock()
        interaction_mm.permissions = discord.Permissions(manage_messages=True)
        self.assertTrue(await pred(interaction_mm))

        # 3. administrator = True -> returns True
        interaction_admin = MagicMock(spec=discord.Interaction)
        interaction_admin.guild = MagicMock()
        interaction_admin.permissions = discord.Permissions(administrator=True)
        self.assertTrue(await pred(interaction_admin))

        # 4. none -> raises MissingPermissions
        interaction_none = MagicMock(spec=discord.Interaction)
        interaction_none.guild = MagicMock()
        interaction_none.permissions = discord.Permissions.none()
        with self.assertRaises(app_commands.MissingPermissions):
            await pred(interaction_none)

        # 5. user.guild_permissions has manage_messages but interaction.permissions does not -> raises MissingPermissions
        interaction_mismatch = MagicMock(spec=discord.Interaction)
        interaction_mismatch.guild = MagicMock()
        interaction_mismatch.permissions = discord.Permissions.none()
        interaction_mismatch.user.guild_permissions = discord.Permissions(manage_messages=True)
        with self.assertRaises(app_commands.MissingPermissions):
            await pred(interaction_mismatch)

    async def test_views_authorization(self):
        cog = MagicMock()
        views_to_test = [
            ("configure options", AddRPOptionsView(user_id=1, rp_type="hug", image_url=None, cog=cog)),
            ("use this menu", EditRPOptionsView(user_id=1, rp_type="hug", cog=cog)),
            ("use this menu", ManageRPView(user_id=1, guild_id=1, rp_types=["hug"], cog=cog)),
            ("navigate this view", ManageRPEntriesView(
                user_id=1, guild_id=1, rp_type="hug", pool="std_text",
                case_type="standard", column="texts", entries=["hug"],
                cog=cog, parent_view=MagicMock()
            )),
        ]

        for expected_msg_prefix, view in views_to_test:
            # Case A: Owner without permission -> interaction_check False, sends new message ephemeral=True
            interaction_no_perm = MagicMock(spec=discord.Interaction)
            interaction_no_perm.user.id = 1
            interaction_no_perm.permissions = discord.Permissions.none()
            interaction_no_perm.response.send_message = AsyncMock()

            res = await view.interaction_check(interaction_no_perm)
            self.assertFalse(res)
            interaction_no_perm.response.send_message.assert_awaited_once_with(
                "You no longer have permission to manage RP entries.",
                ephemeral=True,
            )

            # Case B: Owner with permission -> True
            interaction_with_perm = MagicMock(spec=discord.Interaction)
            interaction_with_perm.user.id = 1
            interaction_with_perm.permissions = discord.Permissions(manage_messages=True)

            res_perm = await view.interaction_check(interaction_with_perm)
            self.assertTrue(res_perm)

            # Case C: Non-owner WITH permission -> False with EXISTING message (user-id check first)
            interaction_non_owner = MagicMock(spec=discord.Interaction)
            interaction_non_owner.user.id = 999
            interaction_non_owner.permissions = discord.Permissions(manage_messages=True)
            interaction_non_owner.response.send_message = AsyncMock()

            res_non = await view.interaction_check(interaction_non_owner)
            self.assertFalse(res_non)
            interaction_non_owner.response.send_message.assert_awaited_once()
            args, kwargs = interaction_non_owner.response.send_message.call_args
            self.assertIn(expected_msg_prefix, args[0])
            self.assertTrue(kwargs.get("ephemeral"))

    async def test_user_id_check_runs_before_permission_check(self):
        cog = MagicMock()
        view = AddRPOptionsView(user_id=1, rp_type="hug", image_url=None, cog=cog)
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user.id = 999  # non-owner
        interaction.permissions = discord.Permissions.none()  # without permission
        interaction.response.send_message = AsyncMock()

        res = await view.interaction_check(interaction)
        self.assertFalse(res)
        interaction.response.send_message.assert_awaited_once()
        args, _ = interaction.response.send_message.call_args
        self.assertIn("Only the person who ran the command can configure options.", args[0])

    async def test_modals_authorization(self):
        cog = MagicMock()
        browser_view = MagicMock()
        browser_view.column = "texts"
        browser_view._show = AsyncMock()

        modals = [
            ("AddRPModal", AddRPModal("hug", "https://i.imgur.com/x.png", "standard", cog)),
            ("EditRPModal", EditRPModal("hug", "std_text", cog)),
            ("EditEntryModal", EditEntryModal(browser_view, "old_entry")),
        ]

        for name, modal in modals:
            # Without permission -> sends new message and never calls handlers/DB
            interaction_no = MagicMock(spec=discord.Interaction)
            interaction_no.permissions = discord.Permissions.none()
            interaction_no.response.send_message = AsyncMock()

            with patch.object(cog, "_handle_add_rp_submission", new=AsyncMock()) as m_add, \
                 patch.object(cog, "_handle_edit_rp_submission", new=AsyncMock()) as m_edit, \
                 patch("views.update_rp_entry", new=AsyncMock()) as m_update:
                await modal.on_submit(interaction_no)
                interaction_no.response.send_message.assert_awaited_once_with(
                    "You no longer have permission to manage RP entries.",
                    ephemeral=True,
                )
                m_add.assert_not_awaited()
                m_edit.assert_not_awaited()
                m_update.assert_not_awaited()

            # With permission -> proceeds (positive control)
            interaction_yes = MagicMock(spec=discord.Interaction)
            interaction_yes.permissions = discord.Permissions(manage_messages=True)
            interaction_yes.response.send_message = AsyncMock()

            with patch.object(cog, "_handle_add_rp_submission", new=AsyncMock()) as m_add, \
                 patch.object(cog, "_handle_edit_rp_submission", new=AsyncMock()) as m_edit, \
                 patch("views.update_rp_entry", new=AsyncMock()) as m_update:
                modal.std_text_input = MagicMock(value="text")
                modal.std_action_input = MagicMock(value="action")
                modal.value_input = MagicMock(value="val")
                modal.input_field = MagicMock(value="val")
                await modal.on_submit(interaction_yes)
                if name == "AddRPModal":
                    m_add.assert_awaited_once()
                elif name == "EditRPModal":
                    m_edit.assert_awaited_once()
                elif name == "EditEntryModal":
                    m_update.assert_awaited_once()

    async def test_remove_type_authorization(self):
        view = ManageRPView(user_id=1, guild_id=1, rp_types=["hug"], cog=MagicMock())
        view.selected_type = "hug"

        # Without permission -> execute_query NOT awaited and message sent
        interaction_no = MagicMock(spec=discord.Interaction)
        interaction_no.permissions = discord.Permissions.none()
        interaction_no.data = {"values": ["remove_type"]}
        interaction_no.response.send_message = AsyncMock()

        with patch("views.execute_query", new=AsyncMock()) as m_exec:
            await view.pool_select_callback(interaction_no)
            m_exec.assert_not_awaited()
            interaction_no.response.send_message.assert_awaited_once_with(
                "You no longer have permission to manage RP entries.",
                ephemeral=True,
            )

        # With permission -> execute_query awaited once
        interaction_yes = MagicMock(spec=discord.Interaction)
        interaction_yes.permissions = discord.Permissions(manage_messages=True)
        interaction_yes.data = {"values": ["remove_type"]}
        interaction_yes.response.edit_message = AsyncMock()

        with patch("views.execute_query", new=AsyncMock()) as m_exec:
            await view.pool_select_callback(interaction_yes)
            m_exec.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
