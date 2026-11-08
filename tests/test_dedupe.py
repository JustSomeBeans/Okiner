import tempfile
import pathlib
import os
import sqlite3
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asqlite
import discord

import migrations
from database import init_connection, set_bot, add_rp_entry, update_rp_entry
from cogs.rp_commands import RPCommands
from views import ActionTextConfirmView, EditEntryModal


class StubBot:
    def __init__(self, db_pool):
        self.db_pool = db_pool


class TestDedupeAndDuplicateHandling(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "rp.db")
        schema_path = pathlib.Path(__file__).resolve().parent.parent / "rp_schema.sql"
        self.schema_sql = schema_path.read_text(encoding="utf-8")

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    def _get_backups(self):
        return [f for f in os.listdir(self.temp_dir.name) if f.startswith("rp.db.bak-") and not f.endswith(("-wal", "-shm"))]

    # 1. test_fresh_db_has_unique_index
    async def test_fresh_db_has_unique_index(self):
        applied = migrations.run_migrations(self.db_path, self.schema_sql)
        self.assertEqual(applied, [1, 2])

        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='ux_roleplay_entries_content'"
            )
            self.assertIsNotNone(cur.fetchone())
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
        finally:
            conn.close()

    # 2. test_migration_removes_duplicates_keeps_lowest_rowid
    async def test_migration_removes_duplicates_keeps_lowest_rowid(self):
        # Build version-1 DB (schema + user_version = 1, NO index)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA user_version = 1")
        conn.executescript(self.schema_sql)
        conn.execute("INSERT INTO rp_types VALUES (1, 'hug')")
        conn.execute("INSERT INTO rp_types VALUES (2, 'hug')")

        conn.execute("INSERT INTO roleplay_entries VALUES (10, 1, 'hug', 'standard', NULL, 't', NULL)")
        conn.execute("INSERT INTO roleplay_entries VALUES (11, 1, 'hug', 'standard', NULL, 't', NULL)")
        conn.execute("INSERT INTO roleplay_entries VALUES (10, 1, 'hug', 'standard', NULL, 't', NULL)")
        conn.execute("INSERT INTO roleplay_entries VALUES (10, 1, 'hug', 'standard', NULL, 'u', NULL)")
        conn.execute("INSERT INTO roleplay_entries VALUES (10, 1, 'hug', 'selfcase', NULL, 't', NULL)")
        conn.execute("INSERT INTO roleplay_entries VALUES (10, 2, 'hug', 'standard', NULL, 't', NULL)")
        conn.commit()

        total_count = conn.execute("SELECT count(*) FROM roleplay_entries").fetchone()[0]
        self.assertEqual(total_count, 6)
        group_count = conn.execute(
            "SELECT count(*) FROM roleplay_entries WHERE guild_id=1 AND type='hug' AND case_type='standard' AND url IS NULL AND texts='t' AND action_texts IS NULL"
        ).fetchone()[0]
        self.assertEqual(group_count, 3)
        conn.close()

        applied = migrations.run_migrations(self.db_path, self.schema_sql)
        self.assertEqual(applied, [2])

        backups = self._get_backups()
        self.assertEqual(len(backups), 1)
        backup_path = os.path.join(self.temp_dir.name, backups[0])

        b_conn = sqlite3.connect(backup_path)
        self.assertEqual(b_conn.execute("SELECT count(*) FROM roleplay_entries").fetchone()[0], 6)
        b_idx = b_conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='ux_roleplay_entries_content'").fetchone()
        self.assertIsNone(b_idx)
        b_conn.close()

        m_conn = sqlite3.connect(self.db_path)
        self.assertEqual(m_conn.execute("SELECT count(*) FROM roleplay_entries").fetchone()[0], 4)
        survivor = m_conn.execute(
            "SELECT user_id FROM roleplay_entries WHERE guild_id=1 AND type='hug' AND case_type='standard' AND texts='t'"
        ).fetchone()
        self.assertEqual(survivor[0], 10)
        self.assertEqual(m_conn.execute("PRAGMA user_version").fetchone()[0], 2)
        m_conn.close()

    # 3. test_index_rejects_duplicates_after_migration
    async def test_index_rejects_duplicates_after_migration(self):
        migrations.run_migrations(self.db_path, self.schema_sql)

        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO rp_types VALUES (1, 'hug'), (2, 'hug')")
        conn.commit()

        conn.execute("INSERT INTO roleplay_entries (user_id, guild_id, type, case_type, texts) VALUES (10, 1, 'hug', 'standard', 'hug text')")
        conn.commit()
        self.assertEqual(conn.execute("SELECT count(*) FROM roleplay_entries").fetchone()[0], 1)

        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO roleplay_entries (user_id, guild_id, type, case_type, texts) VALUES (11, 1, 'hug', 'standard', 'hug text')")
            conn.commit()

        cur = conn.execute("INSERT OR IGNORE INTO roleplay_entries (user_id, guild_id, type, case_type, texts) VALUES (12, 1, 'hug', 'standard', 'hug text')")
        conn.commit()
        self.assertEqual(cur.rowcount, 0)
        self.assertEqual(conn.execute("SELECT count(*) FROM roleplay_entries").fetchone()[0], 1)

        conn.execute("INSERT INTO roleplay_entries (user_id, guild_id, type, case_type, texts) VALUES (10, 1, 'hug', 'selfcase', 'hug text')")
        conn.execute("INSERT INTO roleplay_entries (user_id, guild_id, type, case_type, texts) VALUES (10, 2, 'hug', 'standard', 'hug text')")
        conn.commit()
        self.assertEqual(conn.execute("SELECT count(*) FROM roleplay_entries").fetchone()[0], 3)
        conn.close()

    # 4. test_add_rp_entry_returns_bool
    async def test_add_rp_entry_returns_bool(self):
        migrations.run_migrations(self.db_path, self.schema_sql)
        pool = await asqlite.create_pool(self.db_path, size=1, init=init_connection)
        stub_bot = StubBot(pool)
        set_bot(stub_bot)
        try:
            async with pool.acquire() as conn:
                await conn.execute("INSERT INTO rp_types VALUES (1, 'hug')")
                await conn.commit()

            res1 = await add_rp_entry(10, 1, 'hug', text='hello')
            self.assertTrue(res1)

            res2 = await add_rp_entry(11, 1, 'hug', text='hello')
            self.assertFalse(res2)

            async with pool.acquire() as conn:
                cur = await conn.execute("SELECT count(*) FROM roleplay_entries")
                count = (await cur.fetchone())[0]
                self.assertEqual(count, 1)

            with self.assertRaises(sqlite3.IntegrityError):
                await add_rp_entry(10, 1, 'unknown_type', text='hello')
        finally:
            await pool.close()

    # 5. test_update_rp_entry_collision_raises
    async def test_update_rp_entry_collision_raises(self):
        migrations.run_migrations(self.db_path, self.schema_sql)
        pool = await asqlite.create_pool(self.db_path, size=1, init=init_connection)
        stub_bot = StubBot(pool)
        set_bot(stub_bot)
        try:
            async with pool.acquire() as conn:
                await conn.execute("INSERT INTO rp_types VALUES (1, 'hug')")
                await conn.execute("INSERT INTO roleplay_entries (user_id, guild_id, type, case_type, texts) VALUES (10, 1, 'hug', 'standard', 'a')")
                await conn.execute("INSERT INTO roleplay_entries (user_id, guild_id, type, case_type, texts) VALUES (10, 1, 'hug', 'standard', 'b')")
                await conn.commit()

            with self.assertRaises(sqlite3.IntegrityError):
                await update_rp_entry(1, 'hug', 'standard', 'texts', 'a', 'b')

            async with pool.acquire() as conn:
                cur = await conn.execute("SELECT texts FROM roleplay_entries ORDER BY texts")
                texts = [r[0] for r in (await cur.fetchall())]
                self.assertEqual(texts, ['a', 'b'])

            await update_rp_entry(1, 'hug', 'standard', 'texts', 'a', 'c')
            async with pool.acquire() as conn:
                cur = await conn.execute("SELECT texts FROM roleplay_entries ORDER BY texts")
                texts = [r[0] for r in (await cur.fetchall())]
                self.assertEqual(texts, ['b', 'c'])
        finally:
            await pool.close()

    # 6. Handler tests (mock-based)
    async def test_handle_edit_rp_submission_bool_handling(self):
        cog = RPCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user.id = 10
        interaction.guild_id = 1
        interaction.response.send_message = AsyncMock()

        with patch("database.rp_type_exists", new=AsyncMock(return_value=True)):
            with patch("database.add_rp_entry", new=AsyncMock(return_value=True)) as mock_add:
                await cog._handle_edit_rp_submission(interaction, "hug", "std_text", "hello")
                mock_add.assert_awaited_once()
                args, kwargs = interaction.response.send_message.call_args
                self.assertIn("Added", args[0])

            interaction.response.send_message.reset_mock()
            with patch("database.add_rp_entry", new=AsyncMock(return_value=False)) as mock_add:
                await cog._handle_edit_rp_submission(interaction, "hug", "std_text", "hello")
                mock_add.assert_awaited_once()
                args, kwargs = interaction.response.send_message.call_args
                self.assertEqual(args[0], "That value already exists for this RP type.")

            interaction.response.send_message.reset_mock()
            with patch("cogs.rp_commands.is_valid_image_url", return_value=True), \
                 patch("cogs.rp_commands.is_imgur_page_url", return_value=False), \
                 patch("database.add_rp_entry", new=AsyncMock(return_value=False)) as mock_add:
                await cog._handle_edit_rp_submission(interaction, "hug", "std_img", "https://i.imgur.com/test.png")
                mock_add.assert_awaited_once()
                args, kwargs = interaction.response.send_message.call_args
                self.assertEqual(args[0], "That value already exists for this RP type.")

            interaction.response.send_message.reset_mock()
            with patch("cogs.rp_commands.RPCommands._required_action_tags", return_value=[]), \
                 patch("database.add_rp_entry", new=AsyncMock(return_value=False)) as mock_add:
                await cog._handle_edit_rp_submission(interaction, "hug", "std_action", "hugs {user}")
                mock_add.assert_awaited_once()
                args, kwargs = interaction.response.send_message.call_args
                self.assertEqual(args[0], "That value already exists for this RP type.")

    async def test_action_text_confirm_view_legacy_bool(self):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user.id = 10
        interaction.response.edit_message = AsyncMock()

        with patch("views.add_rp_entry", new=AsyncMock(return_value=False)):
            view = ActionTextConfirmView(
                user_id=10, guild_id=1, rp_type="hug", action_text="action", case_type="standard", on_confirm=None
            )
            await view.confirm.callback(interaction)
            _, edit_kwargs = interaction.response.edit_message.call_args
            self.assertEqual(edit_kwargs.get("content"), "That action text is already saved for this RP type.")

        interaction.response.edit_message.reset_mock()
        with patch("views.add_rp_entry", new=AsyncMock(return_value=True)):
            view = ActionTextConfirmView(
                user_id=10, guild_id=1, rp_type="hug", action_text="action", case_type="standard", on_confirm=None
            )
            await view.confirm.callback(interaction)
            _, edit_kwargs = interaction.response.edit_message.call_args
            self.assertIn("Added", edit_kwargs.get("content"))

    async def test_edit_entry_modal_integrity_error(self):
        browser_view = MagicMock()
        browser_view.column = "texts"
        browser_view.entries = ['a']
        modal = EditEntryModal(browser_view, 'a')
        modal.input_field = MagicMock(value='b')

        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.send_message = AsyncMock()

        with patch("views.update_rp_entry", new=AsyncMock(side_effect=sqlite3.IntegrityError)):
            await modal.on_submit(interaction)
            interaction.response.send_message.assert_awaited_once()
            args, _ = interaction.response.send_message.call_args
            self.assertEqual(args[0], "That value already exists for this RP type.")
            self.assertEqual(browser_view.entries, ['a'])


if __name__ == "__main__":
    unittest.main()
