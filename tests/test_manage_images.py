from __future__ import annotations

import tempfile
import pathlib
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asqlite
import discord

import migrations
from database import init_connection, set_bot
from views import (
    ManageRPView,
    ManageRPEntriesView,
    EditEntryModal,
)

class StubBot:
    def __init__(self, db_pool):
        self.db_pool = db_pool

class TestManageImages(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "rp.db")
        schema_path = pathlib.Path(__file__).resolve().parent.parent / "rp_schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")
        migrations.run_migrations(self.db_path, schema_sql)
        self.pool = await asqlite.create_pool(self.db_path, size=1, init=init_connection)
        set_bot(StubBot(self.pool))

    async def asyncTearDown(self):
        await self.pool.close()
        self.temp_dir.cleanup()

    async def test_url_column_renders_embed_with_image(self):
        view = ManageRPEntriesView(
            user_id=1,
            guild_id=1,
            rp_type="hug",
            pool="std_img",
            case_type="standard",
            column="url",
            entries=["https://i.imgur.com/a.png", "https://i.imgur.com/b.png"],
            cog=MagicMock(),
            parent_view=MagicMock(),
        )
        view.page = 1
        kwargs = view.render_kwargs()
        self.assertIn("embed", kwargs)
        self.assertIsNotNone(kwargs["embed"])
        self.assertEqual(kwargs["embed"].image.url, "https://i.imgur.com/b.png")
        self.assertIn("Entry 2 of 2", kwargs["content"])

    async def test_text_column_has_no_embed(self):
        view = ManageRPEntriesView(
            user_id=1,
            guild_id=1,
            rp_type="hug",
            pool="std_text",
            case_type="standard",
            column="texts",
            entries=["hug text 1"],
            cog=MagicMock(),
            parent_view=MagicMock(),
        )
        kwargs = view.render_kwargs()
        self.assertIn("embed", kwargs)
        self.assertIsNone(kwargs["embed"])
        self.assertEqual(kwargs["content"], view.render_content())

    async def test_backticks_in_url_do_not_break_description(self):
        url_with_backtick = "https://i.imgur.com/a`b.png"
        view = ManageRPEntriesView(
            user_id=1,
            guild_id=1,
            rp_type="hug",
            pool="std_img",
            case_type="standard",
            column="url",
            entries=[url_with_backtick],
            cog=MagicMock(),
            parent_view=MagicMock(),
        )
        kwargs = view.render_kwargs()
        embed = kwargs["embed"]
        self.assertNotIn("`", embed.description)
        self.assertIn("'", embed.description)

    async def test_next_prev_send_embed_for_url_and_clear_for_text(self):
        # URL view
        url_view = ManageRPEntriesView(
            user_id=1,
            guild_id=1,
            rp_type="hug",
            pool="std_img",
            case_type="standard",
            column="url",
            entries=["https://i.imgur.com/a.png", "https://i.imgur.com/b.png"],
            cog=MagicMock(),
            parent_view=MagicMock(),
        )
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.edit_message = AsyncMock()
        interaction.response.is_done = MagicMock(return_value=False)

        await url_view.next_button.callback(interaction)
        interaction.response.edit_message.assert_awaited_once()
        _, kwargs = interaction.response.edit_message.call_args
        self.assertIsNotNone(kwargs.get("embed"))
        self.assertEqual(kwargs["embed"].image.url, "https://i.imgur.com/b.png")

        # Text view
        interaction.response.edit_message.reset_mock()
        text_view = ManageRPEntriesView(
            user_id=1,
            guild_id=1,
            rp_type="hug",
            pool="std_text",
            case_type="standard",
            column="texts",
            entries=["t1", "t2"],
            cog=MagicMock(),
            parent_view=MagicMock(),
        )
        await text_view.next_button.callback(interaction)
        interaction.response.edit_message.assert_awaited_once()
        _, kwargs_text = interaction.response.edit_message.call_args
        self.assertIsNone(kwargs_text.get("embed"))

    async def test_http_exception_falls_back_to_text(self):
        view = ManageRPEntriesView(
            user_id=1,
            guild_id=1,
            rp_type="hug",
            pool="std_img",
            case_type="standard",
            column="url",
            entries=["https://i.imgur.com/a.png"],
            cog=MagicMock(),
            parent_view=MagicMock(),
        )
        interaction = MagicMock(spec=discord.Interaction)
        http_exc = discord.HTTPException(MagicMock(status=400, reason="Bad Request"), "Bad Request")
        interaction.response.edit_message = AsyncMock(side_effect=[http_exc, None])
        interaction.response.is_done = MagicMock(return_value=False)

        await view._show(interaction)
        self.assertEqual(interaction.response.edit_message.await_count, 2)
        second_call_kwargs = interaction.response.edit_message.await_args[1]
        self.assertIsNone(second_call_kwargs.get("embed"))
        self.assertEqual(second_call_kwargs.get("content"), view.render_content())

    async def test_http_exception_when_response_done_reraises(self):
        view = ManageRPEntriesView(
            user_id=1,
            guild_id=1,
            rp_type="hug",
            pool="std_img",
            case_type="standard",
            column="url",
            entries=["https://i.imgur.com/a.png"],
            cog=MagicMock(),
            parent_view=MagicMock(),
        )
        interaction = MagicMock(spec=discord.Interaction)
        http_exc = discord.HTTPException(MagicMock(status=400, reason="Bad Request"), "Bad Request")
        interaction.response.edit_message = AsyncMock(side_effect=http_exc)
        interaction.response.is_done = MagicMock(return_value=True)

        with self.assertRaises(discord.HTTPException):
            await view._show(interaction)
        self.assertEqual(interaction.response.edit_message.await_count, 1)

    async def test_back_and_delete_last_clear_embed(self):
        # Back button
        view = ManageRPEntriesView(
            user_id=1,
            guild_id=1,
            rp_type="hug",
            pool="std_img",
            case_type="standard",
            column="url",
            entries=["https://i.imgur.com/a.png"],
            cog=MagicMock(),
            parent_view=MagicMock(),
        )
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.edit_message = AsyncMock()

        with patch("views.fetch_column", new=AsyncMock(return_value=["hug"])):
            await view.back_button.callback(interaction)

        interaction.response.edit_message.assert_awaited_once()
        _, kwargs_back = interaction.response.edit_message.call_args
        self.assertIn("embed", kwargs_back)
        self.assertIsNone(kwargs_back["embed"])

        # Delete last entry
        interaction.response.edit_message.reset_mock()
        single_view = ManageRPEntriesView(
            user_id=1,
            guild_id=1,
            rp_type="hug",
            pool="std_img",
            case_type="standard",
            column="url",
            entries=["https://i.imgur.com/a.png"],
            cog=MagicMock(),
            parent_view=MagicMock(),
        )
        with patch("views.remove_rp_entry", new=AsyncMock()):
            await single_view.delete_button.callback(interaction)

        interaction.response.edit_message.assert_awaited_once()
        _, kwargs_del = interaction.response.edit_message.call_args
        self.assertIn("embed", kwargs_del)
        self.assertIsNone(kwargs_del["embed"])
        self.assertIsNone(kwargs_del.get("view"))

    async def test_handoff_shows_embed_for_url_pool(self):
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO rp_types VALUES (1, 'hug')")
            await conn.execute("INSERT INTO roleplay_entries (user_id, guild_id, type, case_type, url) VALUES (1, 1, 'hug', 'standard', 'https://i.imgur.com/test.png')")
            await conn.commit()

        view = ManageRPView(user_id=1, guild_id=1, rp_types=["hug"], cog=MagicMock())
        view.selected_type = "hug"

        interaction = MagicMock(spec=discord.Interaction)
        interaction.client.db_pool = self.pool
        interaction.message = MagicMock(spec=discord.Message)
        interaction.data = {"values": ["std_img"]}
        interaction.response.edit_message = AsyncMock()
        interaction.response.is_done = MagicMock(return_value=False)

        await view.pool_select_callback(interaction)

        interaction.response.edit_message.assert_awaited_once()
        _, kwargs = interaction.response.edit_message.call_args
        self.assertIsNotNone(kwargs.get("embed"))
        self.assertEqual(kwargs["embed"].image.url, "https://i.imgur.com/test.png")

    async def test_edit_modal_success_uses_show(self):
        browser_view = ManageRPEntriesView(
            user_id=1,
            guild_id=1,
            rp_type="hug",
            pool="std_img",
            case_type="standard",
            column="url",
            entries=["https://i.imgur.com/old.png"],
            cog=MagicMock(),
            parent_view=MagicMock(),
        )
        browser_view.message = MagicMock(spec=discord.Message)

        modal = EditEntryModal(browser_view, "https://i.imgur.com/old.png")
        modal.input_field = MagicMock(value="https://i.imgur.com/new.png")

        interaction = MagicMock(spec=discord.Interaction)
        interaction.permissions = discord.Permissions(manage_messages=True)
        interaction.response.edit_message = AsyncMock()
        interaction.response.is_done = MagicMock(return_value=False)

        with patch("views.update_rp_entry", new=AsyncMock()) as m_update:
            await modal.on_submit(interaction)
            m_update.assert_awaited_once()

        interaction.response.edit_message.assert_awaited_once()
        _, kwargs = interaction.response.edit_message.call_args
        self.assertIsNotNone(kwargs.get("embed"))
        self.assertEqual(kwargs["embed"].image.url, "https://i.imgur.com/new.png")

if __name__ == "__main__":
    unittest.main()
