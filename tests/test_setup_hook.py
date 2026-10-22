import tempfile
import pathlib
import os
import sqlite3
import unittest
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import database
import migrations
from bot import OkinerBot
from config import DB_PATH, SCHEMA_PATH


class TestSetupHook(unittest.IsolatedAsyncioTestCase):
    # 1. test_setup_hook_order
    async def test_setup_hook_order(self):
        bot = OkinerBot()
        calls = []

        def mock_run_migrations(db_path, schema_sql):
            calls.append(("migrate", (db_path, schema_sql)))
            return [1]

        mock_create_pool = AsyncMock(side_effect=lambda *args, **kwargs: calls.append(("pool", kwargs)) or MagicMock())
        mock_set_bot = MagicMock(side_effect=lambda b: calls.append(("set_bot", b)))
        mock_assert_pragmas = AsyncMock(side_effect=lambda: calls.append(("assert_pragmas", None)))
        mock_find_multi = AsyncMock(return_value=[])

        with patch("bot.migrations.run_migrations", new=mock_run_migrations), \
             patch("bot.asqlite.create_pool", new=mock_create_pool), \
             patch("bot.database.set_bot", new=mock_set_bot), \
             patch("bot.database.assert_connection_pragmas", new=mock_assert_pragmas), \
             patch("bot.database.find_multi_marriage_users", new=mock_find_multi), \
             patch.object(bot, "load_extension", new=AsyncMock()) as mock_load_ext:

            await bot.setup_hook()

            # Assert recorded order: migrate BEFORE pool
            action_types = [c[0] for c in calls]
            self.assertIn("migrate", action_types)
            self.assertIn("pool", action_types)
            migrate_idx = action_types.index("migrate")
            pool_idx = action_types.index("pool")
            self.assertLess(migrate_idx, pool_idx)

            # Assert migrate args
            migrate_call = [c for c in calls if c[0] == "migrate"][0]
            expected_schema = SCHEMA_PATH.read_text(encoding="utf-8")
            self.assertEqual(migrate_call[1], (DB_PATH, expected_schema))

            # Assert create_pool called with kwargs containing init=database.init_connection
            pool_call = [c for c in calls if c[0] == "pool"][0]
            self.assertEqual(pool_call[1].get("init"), database.init_connection)

            # Assert assert_connection_pragmas awaited once
            mock_assert_pragmas.assert_awaited_once()

            # Assert load_extension awaited 4 times with four cog names
            self.assertEqual(mock_load_ext.await_count, 4)
            expected_cogs = [
                "cogs.rp_commands",
                "cogs.family_commands",
                "cogs.moderation",
                "cogs.behavior",
            ]
            awaited_cogs = [call.args[0] for call in mock_load_ext.await_args_list]
            self.assertEqual(awaited_cogs, expected_cogs)

    # 2. test_migration_failure_is_fail_closed
    async def test_migration_failure_is_fail_closed(self):
        bot = OkinerBot()
        mock_create_pool = AsyncMock()

        with patch("bot.migrations.run_migrations", side_effect=RuntimeError("boom")), \
             patch("bot.asqlite.create_pool", new=mock_create_pool), \
             patch.object(bot, "load_extension", new=AsyncMock()) as mock_load_ext:

            with self.assertRaises(RuntimeError):
                await bot.setup_hook()

            mock_create_pool.assert_not_awaited()
            mock_load_ext.assert_not_awaited()

    # 3. test_setup_hook_has_no_inline_migrations
    def test_setup_hook_has_no_inline_migrations(self):
        source = inspect.getsource(OkinerBot.setup_hook)
        self.assertNotIn("ALTER TABLE", source)
        self.assertNotIn("DROP TRIGGER", source)
        self.assertNotIn("executescript", source)
        self.assertNotIn("rp_self_cases", source)
        self.assertIn("init=database.init_connection", source)

    # 4. test_schema_has_no_rp_self_cases
    def test_schema_has_no_rp_self_cases(self):
        schema_path = pathlib.Path(__file__).resolve().parent.parent / "rp_schema.sql"
        schema_text = schema_path.read_text(encoding="utf-8")
        self.assertNotIn("rp_self_cases", schema_text)

        # Positive control: migrations.py source still contains rp_self_cases
        mig_path = pathlib.Path(__file__).resolve().parent.parent / "migrations.py"
        mig_text = mig_path.read_text(encoding="utf-8")
        self.assertIn("rp_self_cases", mig_text)

    # 5. test_schema_creates_no_legacy_table_on_fresh_db
    def test_schema_creates_no_legacy_table_on_fresh_db(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = os.path.join(temp_dir, "rp.db")
            schema_path = pathlib.Path(__file__).resolve().parent.parent / "rp_schema.sql"
            schema_sql = schema_path.read_text(encoding="utf-8")

            migrations.run_migrations(db_path, schema_sql)

            conn = sqlite3.connect(db_path)
            try:
                cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = {row[0] for row in cur.fetchall()}
                self.assertNotIn("rp_self_cases", tables)
                for t in tables:
                    self.assertFalse(t.endswith("_legacy"))
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
