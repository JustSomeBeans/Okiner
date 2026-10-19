import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import discord
import sqlite3
from cogs.rp_commands import RPCommands, build_rp_payload
from views import ActionTextConfirmView
from config import STANDARD_CASE, SELF_CASE, NULL_CASE, MAX_TEXT_LENGTH

class TestRPAdd(unittest.IsolatedAsyncioTestCase):
    def test_build_rp_payload_all_cases(self):
        # A case where std, self and null texts/actions are all given yields the exact expected list
        payload = build_rp_payload(
            image_url="https://i.imgur.com/test.png",
            std_text="std text",
            std_action="std action {user} {target}",
            case_mode="standard_self_null",
            self_text="self text",
            null_text="null text",
        )
        expected = [
            {"case_type": STANDARD_CASE, "url": "https://i.imgur.com/test.png", "text": None, "action_text": None},
            {"case_type": STANDARD_CASE, "url": None, "text": "std text", "action_text": None},
            {"case_type": STANDARD_CASE, "url": None, "text": None, "action_text": "std action {user} {target}"},
            {"case_type": SELF_CASE, "url": None, "text": "self text", "action_text": None},
            {"case_type": NULL_CASE, "url": None, "text": "null text", "action_text": None},
        ]
        self.assertEqual(payload, expected)

    async def test_no_warning_path(self):
        cog = RPCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 123
        interaction.user.id = 456
        interaction.response.send_message = AsyncMock()

        with patch("database.rp_type_exists", new=AsyncMock(return_value=False)) as mock_exists, \
             patch("database.create_rp_type_with_entries", new=AsyncMock()) as mock_create, \
             patch("database.add_rp_type", new=AsyncMock()) as mock_add_type, \
             patch("database.add_rp_entry", new=AsyncMock()) as mock_add_entry:

            await cog._handle_add_rp_submission(
                interaction,
                rp_type="hug",
                image_url="https://i.imgur.com/a.png",
                std_text="hugs",
                std_action="hugs {user} {target}",
                case_mode="standard",
                self_text=None,
                null_text=None,
            )

            mock_exists.assert_awaited_once()
            mock_create.assert_awaited_once()
            mock_add_type.assert_not_awaited()
            mock_add_entry.assert_not_awaited()
            interaction.response.send_message.assert_awaited_once()

    async def test_warning_path_and_confirm(self):
        cog = RPCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 123
        interaction.user.id = 456
        interaction.response.send_message = AsyncMock()
        interaction.original_response = AsyncMock()

        with patch("database.rp_type_exists", new=AsyncMock(return_value=False)), \
             patch("database.create_rp_type_with_entries", new=AsyncMock()) as mock_create, \
             patch("database.add_rp_type", new=AsyncMock()) as mock_add_type, \
             patch("database.add_rp_entry", new=AsyncMock()) as mock_add_entry:

            await cog._handle_add_rp_submission(
                interaction,
                rp_type="hug",
                image_url="https://i.imgur.com/a.png",
                std_text="hugs",
                std_action="missing tags action", # Missing {user} {target}
                case_mode="standard_self_null",
                self_text="self text",
                null_text="null text",
            )

            # At warning sent time, create not awaited and no add_* awaited
            mock_create.assert_not_awaited()
            mock_add_type.assert_not_awaited()
            mock_add_entry.assert_not_awaited()

            # Capture view from send_message kwargs
            _, kwargs = interaction.response.send_message.call_args
            view = kwargs.get("view")
            self.assertIsInstance(view, ActionTextConfirmView)

            # Invoke confirm callback
            confirm_interaction = MagicMock(spec=discord.Interaction)
            confirm_interaction.guild_id = 123
            confirm_interaction.user.id = 456
            confirm_interaction.response.edit_message = AsyncMock()

            await view.confirm.callback(confirm_interaction)
            mock_create.assert_awaited_once()

    async def test_cancel_path(self):
        cog = RPCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 123
        interaction.user.id = 456
        interaction.response.send_message = AsyncMock()
        interaction.original_response = AsyncMock()

        with patch("database.rp_type_exists", new=AsyncMock(return_value=False)), \
             patch("database.create_rp_type_with_entries", new=AsyncMock()) as mock_create:

            await cog._handle_add_rp_submission(
                interaction,
                rp_type="hug",
                image_url="https://i.imgur.com/a.png",
                std_text="hugs",
                std_action="missing tags action",
                case_mode="standard",
                self_text=None,
                null_text=None,
            )

            _, kwargs = interaction.response.send_message.call_args
            view = kwargs.get("view")

            cancel_interaction = MagicMock(spec=discord.Interaction)
            cancel_interaction.response.edit_message = AsyncMock()

            await view.cancel.callback(cancel_interaction)
            mock_create.assert_not_awaited()

    async def test_create_raising_integrity_error(self):
        cog = RPCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 123
        interaction.user.id = 456
        interaction.response.send_message = AsyncMock()

        with patch("database.rp_type_exists", new=AsyncMock(return_value=False)), \
             patch("database.create_rp_type_with_entries", new=AsyncMock(side_effect=sqlite3.IntegrityError)):

            await cog._handle_add_rp_submission(
                interaction,
                rp_type="hug",
                image_url="https://i.imgur.com/a.png",
                std_text="hugs",
                std_action="hugs {user} {target}",
                case_mode="standard",
                self_text=None,
                null_text=None,
            )

            interaction.response.send_message.assert_awaited_once()
            args, _ = interaction.response.send_message.call_args
            self.assertIn("already exists", args[0])

    async def test_validation_failure_too_long(self):
        cog = RPCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 123
        interaction.user.id = 456
        interaction.response.send_message = AsyncMock()

        with patch("database.rp_type_exists", new=AsyncMock(return_value=False)), \
             patch("database.create_rp_type_with_entries", new=AsyncMock()) as mock_create, \
             patch("database.add_rp_type", new=AsyncMock()) as mock_add_type, \
             patch("database.add_rp_entry", new=AsyncMock()) as mock_add_entry:

            await cog._handle_add_rp_submission(
                interaction,
                rp_type="hug",
                image_url="https://i.imgur.com/a.png",
                std_text="x" * 2000, # Too long
                std_action="hugs {user} {target}",
                case_mode="standard",
                self_text=None,
                null_text=None,
            )

            mock_create.assert_not_awaited()
            mock_add_type.assert_not_awaited()
            mock_add_entry.assert_not_awaited()

    async def test_legacy_path_action_text_confirm_view(self):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user.id = 456
        interaction.response.edit_message = AsyncMock()

        with patch("views.add_rp_entry", new=AsyncMock()) as mock_add_entry:
            view = ActionTextConfirmView(
                user_id=456,
                guild_id=123,
                rp_type="hug",
                action_text="action",
                case_type="standard",
                on_confirm=None,
            )
            await view.confirm.callback(interaction)
            mock_add_entry.assert_awaited_once()

    async def test_existing_type_precheck_path(self):
        cog = RPCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 123
        interaction.response.send_message = AsyncMock()

        with patch("database.rp_type_exists", new=AsyncMock(return_value=True)), \
             patch("database.create_rp_type_with_entries", new=AsyncMock()) as mock_create:

            await cog._handle_add_rp_submission(
                interaction,
                rp_type="hug",
                image_url="https://i.imgur.com/a.png",
                std_text="hugs",
                std_action="hugs {user} {target}",
                case_mode="standard",
                self_text=None,
                null_text=None,
            )

            mock_create.assert_not_awaited()
            interaction.response.send_message.assert_awaited_once()
            args, _ = interaction.response.send_message.call_args
            self.assertIn("already exists", args[0])

    async def test_warning_path_and_confirm_full_payload(self):
        cog = RPCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 123
        interaction.user.id = 456
        interaction.response.send_message = AsyncMock()
        interaction.original_response = AsyncMock()

        with patch("database.rp_type_exists", new=AsyncMock(return_value=False)), \
             patch("database.create_rp_type_with_entries", new=AsyncMock()) as mock_create:

            await cog._handle_add_rp_submission(
                interaction,
                rp_type="hug",
                image_url="https://i.imgur.com/test.png",
                std_text="std text",
                std_action="missing tags",
                case_mode="standard_self_null",
                self_text="self text",
                null_text="null text",
            )

            _, kwargs = interaction.response.send_message.call_args
            view = kwargs.get("view")
            self.assertIsInstance(view, ActionTextConfirmView)

            confirm_interaction = MagicMock(spec=discord.Interaction)
            confirm_interaction.guild_id = 123
            confirm_interaction.user.id = 456
            confirm_interaction.response.edit_message = AsyncMock()

            await view.confirm.callback(confirm_interaction)
            expected_payload = [
                {"case_type": STANDARD_CASE, "url": "https://i.imgur.com/test.png", "text": None, "action_text": None},
                {"case_type": STANDARD_CASE, "url": None, "text": "std text", "action_text": None},
                {"case_type": STANDARD_CASE, "url": None, "text": None, "action_text": "missing tags"},
                {"case_type": SELF_CASE, "url": None, "text": "self text", "action_text": None},
                {"case_type": NULL_CASE, "url": None, "text": "null text", "action_text": None},
            ]
            mock_create.assert_awaited_once_with(123, 456, "hug", expected_payload)
            confirm_interaction.response.edit_message.assert_awaited_once()
            _, edit_kwargs = confirm_interaction.response.edit_message.call_args
            self.assertIn("despite missing tags", edit_kwargs.get("content", ""))

    async def test_warning_path_confirm_integrity_error(self):
        cog = RPCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 123
        interaction.user.id = 456
        interaction.response.send_message = AsyncMock()

        with patch("database.rp_type_exists", new=AsyncMock(return_value=False)), \
             patch("database.create_rp_type_with_entries", new=AsyncMock(side_effect=sqlite3.IntegrityError)):

            await cog._handle_add_rp_submission(
                interaction,
                rp_type="hug",
                image_url=None,
                std_text="std",
                std_action="missing",
                case_mode="standard",
                self_text=None,
                null_text=None,
            )

            _, kwargs = interaction.response.send_message.call_args
            view = kwargs.get("view")

            confirm_interaction = MagicMock(spec=discord.Interaction)
            confirm_interaction.user.id = 456
            confirm_interaction.response.edit_message = AsyncMock()

            await view.confirm.callback(confirm_interaction)
            confirm_interaction.response.edit_message.assert_awaited_once()
            _, edit_kwargs = confirm_interaction.response.edit_message.call_args
            self.assertEqual(edit_kwargs.get("content"), "That RP type already exists.")

    async def test_legacy_view_integrity_error(self):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user.id = 456
        interaction.response.edit_message = AsyncMock()

        with patch("views.add_rp_entry", new=AsyncMock(side_effect=sqlite3.IntegrityError)) as mock_add_entry:
            view = ActionTextConfirmView(
                user_id=456,
                guild_id=123,
                rp_type="hug",
                action_text="action",
                case_type="standard",
                on_confirm=None,
            )
            await view.confirm.callback(interaction)
            mock_add_entry.assert_awaited_once()
            interaction.response.edit_message.assert_awaited_once()
            _, edit_kwargs = interaction.response.edit_message.call_args
            self.assertEqual(edit_kwargs.get("content"), "That RP type no longer exists.")

    async def test_validation_failure_selfcase_nullcase_too_long(self):
        cog = RPCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 123
        interaction.user.id = 456
        interaction.response.send_message = AsyncMock()

        with patch("database.rp_type_exists", new=AsyncMock(return_value=False)), \
             patch("database.create_rp_type_with_entries", new=AsyncMock()) as mock_create:

            await cog._handle_add_rp_submission(
                interaction,
                rp_type="hug",
                image_url=None,
                std_text="std",
                std_action="hugs {user} {target}",
                case_mode="self",
                self_text="x" * (MAX_TEXT_LENGTH + 1),
                null_text=None,
            )
            mock_create.assert_not_awaited()
            interaction.response.send_message.assert_awaited_once()
            args, _ = interaction.response.send_message.call_args
            self.assertIn("Selfcase", args[0])

            interaction.response.send_message.reset_mock()
            await cog._handle_add_rp_submission(
                interaction,
                rp_type="hug",
                image_url=None,
                std_text="std",
                std_action="hugs {user} {target}",
                case_mode="null",
                self_text=None,
                null_text="x" * (MAX_TEXT_LENGTH + 1),
            )
            mock_create.assert_not_awaited()
            interaction.response.send_message.assert_awaited_once()
            args, _ = interaction.response.send_message.call_args
            self.assertIn("Nullcase", args[0])

    async def test_view_is_finished_on_confirm_and_cancel(self):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user.id = 456
        interaction.response.edit_message = AsyncMock()

        view1 = ActionTextConfirmView(
            user_id=456,
            guild_id=123,
            rp_type="hug",
            action_text="action",
            case_type="standard",
            on_confirm=AsyncMock(),
        )
        self.assertFalse(view1.is_finished())
        await view1.confirm.callback(interaction)
        self.assertTrue(view1.is_finished())

        view2 = ActionTextConfirmView(
            user_id=456,
            guild_id=123,
            rp_type="hug",
            action_text="action",
            case_type="standard",
            on_confirm=None,
        )
        self.assertFalse(view2.is_finished())
        await view2.cancel.callback(interaction)
        self.assertTrue(view2.is_finished())
        _, edit_kwargs = interaction.response.edit_message.call_args
        self.assertEqual(edit_kwargs.get("content"), "Action text addition cancelled.")

if __name__ == "__main__":
    unittest.main()
