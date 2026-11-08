from __future__ import annotations

import tempfile
import pathlib
import os
import sqlite3
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asqlite
import discord

import migrations
from database import init_connection
from autocomplete import rp_type_autocomplete
from views import ManageRPView


class StubBot:
    def __init__(self, db_pool):
        self.db_pool = db_pool


class TestAutocompleteAndManage(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "rp.db")
        schema_path = pathlib.Path(__file__).resolve().parent.parent / "rp_schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")
        migrations.run_migrations(self.db_path, schema_sql)
        self.pool = await asqlite.create_pool(self.db_path, size=1, init=init_connection)

    async def asyncTearDown(self):
        await self.pool.close()
        self.temp_dir.cleanup()

    async def test_underscore_is_literal(self):
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO rp_types VALUES (1, 'a_b')")
            await conn.execute("INSERT INTO rp_types VALUES (1, 'axb')")
            await conn.commit()

        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 1
        interaction.client = StubBot(self.pool)

        choices = await rp_type_autocomplete(interaction, "a_b")
        self.assertEqual(len(choices), 1)
        self.assertEqual(choices[0].name, "a_b")

        # Positive control: raw sqlite3 query WITHOUT escaping matches both 'a_b' and 'axb'
        raw_conn = sqlite3.connect(self.db_path)
        try:
            cur = raw_conn.execute(
                "SELECT type FROM rp_types WHERE guild_id = 1 AND LOWER(type) LIKE ?",
                ("%a_b%",)
            )
            raw_rows = [r[0] for r in cur.fetchall()]
            self.assertIn("a_b", raw_rows)
            self.assertIn("axb", raw_rows)
        finally:
            raw_conn.close()

    async def test_percent_is_literal(self):
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO rp_types VALUES (1, 'hug')")
            await conn.execute("INSERT INTO rp_types VALUES (1, 'slap')")
            await conn.commit()

        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 1
        interaction.client = StubBot(self.pool)

        choices = await rp_type_autocomplete(interaction, "%")
        self.assertEqual(choices, [])

        choices_a = await rp_type_autocomplete(interaction, "sl")
        self.assertEqual(len(choices_a), 1)
        self.assertEqual(choices_a[0].name, "slap")

    async def test_backslash_is_literal(self):
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO rp_types VALUES (1, 'a\\b')")
            await conn.commit()

        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 1
        interaction.client = StubBot(self.pool)

        choices = await rp_type_autocomplete(interaction, "a\\b")
        self.assertEqual(len(choices), 1)
        self.assertEqual(choices[0].name, "a\\b")

    async def test_normal_search_still_works(self):
        async with self.pool.acquire() as conn:
            for i in range(30):
                await conn.execute("INSERT INTO rp_types VALUES (1, ?)", (f"hug_{i:02d}",))
            await conn.execute("INSERT INTO rp_types VALUES (1, 'pat')")
            await conn.execute("INSERT INTO rp_types VALUES (2, 'hug_other')")
            await conn.commit()

        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 1
        interaction.client = StubBot(self.pool)

        choices = await rp_type_autocomplete(interaction, "HUG")
        self.assertLessEqual(len(choices), 25)
        self.assertTrue(all("hug" in c.name.lower() for c in choices))
        # Ensure guild 2 not included
        self.assertNotIn("hug_other", [c.name for c in choices])

    async def test_unknown_pool_value_is_handled(self):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user.id = 10
        interaction.guild_id = 1
        interaction.data = {"values": ["bogus"]}
        interaction.response.send_message = AsyncMock()
        interaction.client = StubBot(self.pool)

        view = ManageRPView(cog=MagicMock(), user_id=10, guild_id=1, rp_types=["hug"])
        view.selected_type = "hug"

        # Patch acquire to raise if called, asserting no DB access
        with patch.object(self.pool, "acquire", side_effect=AssertionError("DB accessed")):
            await view.pool_select_callback(interaction)

        interaction.response.send_message.assert_awaited_once_with(
            "That option isn't available anymore. Please run /manage_rp again.",
            ephemeral=True,
        )

    async def test_known_pool_value_still_works(self):
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO rp_types VALUES (1, 'hug')")
            await conn.execute("INSERT INTO roleplay_entries (user_id, guild_id, type, case_type, texts) VALUES (10, 1, 'hug', 'standard', 'hello')")
            await conn.commit()

        interaction = MagicMock(spec=discord.Interaction)
        interaction.user.id = 10
        interaction.guild_id = 1
        interaction.data = {"values": ["std_text"]}
        interaction.response.edit_message = AsyncMock()
        interaction.client = StubBot(self.pool)

        view = ManageRPView(cog=MagicMock(), user_id=10, guild_id=1, rp_types=["hug"])
        view.selected_type = "hug"

        with patch("views.ManageRPEntriesView") as mock_entries_view:
            mock_entries_view.return_value._show = AsyncMock()
            await view.pool_select_callback(interaction)
            mock_entries_view.assert_called_once()


if __name__ == "__main__":
    unittest.main()
