import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import discord
import tempfile
import pathlib
import os
import asqlite

import migrations
from database import init_connection, set_bot
from views import (
    ActionTextConfirmView,
    RPBackView,
    AddRPOptionsView,
    EditRPOptionsView,
    ManageRPView,
    ManageRPEntriesView,
    MarriageConfirmView,
    AdoptionConfirmView,
)

class StubBot:
    def __init__(self, db_pool):
        self.db_pool = db_pool

class TestViewRobustness(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "rp.db")
        schema_path = pathlib.Path(__file__).resolve().parent.parent / "rp_schema.sql"
        self.schema_sql = schema_path.read_text(encoding="utf-8")
        migrations.run_migrations(self.db_path, self.schema_sql)
        self.pool = await asqlite.create_pool(self.db_path, size=1, init=init_connection)
        set_bot(StubBot(self.pool))

    async def asyncTearDown(self):
        await self.pool.close()
        self.temp_dir.cleanup()

    def _construct_views(self):
        cog = MagicMock()
        return [
            ActionTextConfirmView(user_id=1, guild_id=1, rp_type="hug", action_text="hug"),
            RPBackView(cog=cog, rp_type="hug", original_actor_id=1, target_id=2, guild_id=1),
            AddRPOptionsView(user_id=1, rp_type="hug", image_url=None, cog=cog),
            EditRPOptionsView(user_id=1, rp_type="hug", cog=cog),
            ManageRPView(user_id=1, guild_id=1, rp_types=["hug"], cog=cog),
            ManageRPEntriesView(
                user_id=1,
                guild_id=1,
                rp_type="hug",
                pool="std_text",
                case_type="standard",
                column="texts",
                entries=["hug"],
                cog=cog,
                parent_view=MagicMock(),
            ),
        ]

    async def test_every_view_has_message_attribute(self):
        for view in self._construct_views():
            self.assertTrue(hasattr(view, "message"))
            self.assertIsNone(view.message)

    async def test_on_timeout_with_no_message_does_not_raise(self):
        for view in self._construct_views():
            # Add a button child with disabled attribute to test child disabling
            btn = discord.ui.Button(label="Test")
            view.add_item(btn)
            await view.on_timeout()
            self.assertTrue(btn.disabled)

    async def test_on_timeout_swallows_http_errors(self):
        not_found = discord.NotFound(MagicMock(status=404, reason="Not Found"), "Not Found")
        http_exc = discord.HTTPException(MagicMock(status=500, reason="Error"), "Error")

        for view in self._construct_views():
            msg = MagicMock()
            msg.edit = AsyncMock(side_effect=[not_found, http_exc])
            view.message = msg

            # First timeout call hits NotFound, should be caught without raising
            await view.on_timeout()
            # Second timeout call hits HTTPException, should be caught without raising
            await view.on_timeout()

    async def test_on_timeout_edits_message(self):
        for view in self._construct_views():
            msg = MagicMock()
            msg.edit = AsyncMock()
            view.message = msg

            await view.on_timeout()
            msg.edit.assert_awaited_once()

    async def test_timeout_texts_preserved(self):
        # ActionTextConfirmView
        view_action = ActionTextConfirmView(user_id=1, guild_id=1, rp_type="hug", action_text="hug")
        msg_action = MagicMock()
        msg_action.edit = AsyncMock()
        view_action.message = msg_action
        await view_action.on_timeout()
        _, kwargs_action = msg_action.edit.call_args
        self.assertEqual(kwargs_action.get("content"), "Confirmation timed out. Run the command again if you still want to add it.")
        self.assertEqual(kwargs_action.get("view"), view_action)

        # AddRPOptionsView
        view_add = AddRPOptionsView(user_id=1, rp_type="hug", image_url=None, cog=MagicMock())
        msg_add = MagicMock()
        msg_add.edit = AsyncMock()
        view_add.message = msg_add
        await view_add.on_timeout()
        _, kwargs_add = msg_add.edit.call_args
        self.assertEqual(kwargs_add.get("content"), "Configuration timed out.")
        self.assertEqual(kwargs_add.get("view"), view_add)

    async def test_marriage_and_adoption_timeout_failures_isolated(self):
        target = MagicMock(spec=discord.User)
        target.mention = "@target"
        interaction = MagicMock(spec=discord.Interaction)
        not_found = discord.NotFound(MagicMock(status=404, reason="Not Found"), "Not Found")
        http_exc = discord.HTTPException(MagicMock(status=500, reason="Error"), "Error")

        for view_cls in [MarriageConfirmView, AdoptionConfirmView]:
            # Case 1: edit_original_response raises NotFound, followup.send succeeds
            interaction.edit_original_response = AsyncMock(side_effect=not_found)
            interaction.followup.send = AsyncMock()

            view = view_cls(interaction, target)
            await view.on_timeout()
            interaction.edit_original_response.assert_awaited_once()
            interaction.followup.send.assert_awaited_once()

            # Case 2: edit_original_response succeeds, followup.send raises HTTPException
            interaction.edit_original_response = AsyncMock()
            interaction.followup.send = AsyncMock(side_effect=http_exc)

            view = view_cls(interaction, target)
            await view.on_timeout()
            interaction.edit_original_response.assert_awaited_once()
            interaction.followup.send.assert_awaited_once()

    async def test_manage_handoff_sets_message(self):
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO rp_types VALUES (1, 'hug')")
            await conn.execute("INSERT INTO roleplay_entries (user_id, guild_id, type, case_type, texts) VALUES (1, 1, 'hug', 'standard', 'hug text')")
            await conn.commit()

        view = ManageRPView(user_id=1, guild_id=1, rp_types=["hug"], cog=MagicMock())
        view.selected_type = "hug"

        interaction = MagicMock(spec=discord.Interaction)
        interaction.client.db_pool = self.pool
        sentinel_message = MagicMock(spec=discord.Message)
        interaction.message = sentinel_message
        interaction.data = {"values": ["std_text"]}
        interaction.response.edit_message = AsyncMock()

        captured_views = []
        async def mock_edit(*args, **kwargs):
            if "view" in kwargs and kwargs["view"] is not None:
                captured_views.append(kwargs["view"])
            elif len(args) > 1 and isinstance(args[1], discord.ui.View):
                captured_views.append(args[1])

        interaction.response.edit_message = AsyncMock(side_effect=mock_edit)

        await view.pool_select_callback(interaction)

        self.assertTrue(len(captured_views) > 0)
        entries_view = captured_views[0]
        self.assertIsInstance(entries_view, ManageRPEntriesView)
        self.assertEqual(entries_view.message, sentinel_message)

    async def test_entries_back_button_sets_message(self):
        view = ManageRPEntriesView(
            user_id=1,
            guild_id=1,
            rp_type="hug",
            pool="std_text",
            case_type="standard",
            column="texts",
            entries=["hug text"],
            cog=MagicMock(),
            parent_view=MagicMock(),
        )

        interaction = MagicMock(spec=discord.Interaction)
        sentinel_message = MagicMock(spec=discord.Message)
        interaction.message = sentinel_message
        interaction.response.edit_message = AsyncMock()

        captured_views = []
        async def mock_edit(*args, **kwargs):
            if "view" in kwargs and kwargs["view"] is not None:
                captured_views.append(kwargs["view"])

        interaction.response.edit_message = AsyncMock(side_effect=mock_edit)

        with patch("views.fetch_column", new=AsyncMock(return_value=["hug"])):
            await view.back_button.callback(interaction)

        self.assertTrue(len(captured_views) > 0)
        new_manage_view = captured_views[0]
        self.assertIsInstance(new_manage_view, ManageRPView)
        self.assertEqual(new_manage_view.message, sentinel_message)

if __name__ == "__main__":
    unittest.main()
