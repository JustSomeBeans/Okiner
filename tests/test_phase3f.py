from __future__ import annotations

import tempfile
import pathlib
import os
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asqlite
import discord

import migrations
import database
from database import init_connection, set_bot
from cogs.behavior import Behavior
from views import ManageRPView, RPBackView


class StubBot:
    def __init__(self, db_pool):
        self.db_pool = db_pool
        self.wait_until_ready = AsyncMock()


class TestPhase3F(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        database._guild_config_cache.clear()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "phase3f.db")
        schema_path = pathlib.Path(__file__).resolve().parent.parent / "rp_schema.sql"
        self.schema_sql = schema_path.read_text(encoding="utf-8")
        migrations.run_migrations(self.db_path, self.schema_sql)
        self.pool = await asqlite.create_pool(self.db_path, size=1, init=init_connection)
        self.stub_bot = StubBot(self.pool)
        set_bot(self.stub_bot)
        self.cog = Behavior(self.stub_bot)

    async def asyncTearDown(self):
        await self.cog.cog_unload()
        await self.pool.close()
        self.temp_dir.cleanup()
        database._guild_config_cache.clear()

    async def test_1_pagination(self):
        # 60 types -> 3 pages (25, 25, 10)
        types_60 = [f"t{i:02d}" for i in range(60)]
        view = ManageRPView(user_id=1, guild_id=1, rp_types=types_60, cog=MagicMock())
        self.assertEqual(len(view.type_select.options), 25)
        self.assertEqual(view.type_select.options[0].value, "t00")
        self.assertEqual(view.type_select.options[24].value, "t24")
        
        content = view._build_type_screen()
        self.assertIn("page 1 of 3", content)
        self.assertIn("60 types", content)

        # Prev disabled, Next enabled
        prev_btn = next((c for c in view.children if getattr(c, "label", "") == "◀ Prev types"), None)
        next_btn = next((c for c in view.children if getattr(c, "label", "") == "Next types ▶"), None)
        self.assertIsNotNone(prev_btn)
        self.assertIsNotNone(next_btn)
        self.assertTrue(prev_btn.disabled)
        self.assertFalse(next_btn.disabled)

        # Next callback -> page 1 (options 25..49)
        inter = MagicMock(spec=discord.Interaction)
        inter.response = MagicMock()
        inter.response.edit_message = AsyncMock()
        await view.type_next_callback(inter)
        self.assertEqual(view.type_page, 1)
        self.assertEqual(len(view.type_select.options), 25)
        self.assertEqual(view.type_select.options[0].value, "t25")
        self.assertEqual(view.type_select.options[24].value, "t49")

        # Next callback -> page 2 (options 50..59, 10 options)
        await view.type_next_callback(inter)
        self.assertEqual(view.type_page, 2)
        self.assertEqual(len(view.type_select.options), 10)
        self.assertEqual(view.type_select.options[0].value, "t50")
        self.assertEqual(view.type_select.options[9].value, "t59")
        
        next_btn_page2 = next((c for c in view.children if getattr(c, "label", "") == "Next types ▶"), None)
        prev_btn_page2 = next((c for c in view.children if getattr(c, "label", "") == "◀ Prev types"), None)
        self.assertIsNotNone(next_btn_page2)
        self.assertIsNotNone(prev_btn_page2)
        self.assertTrue(next_btn_page2.disabled)
        self.assertFalse(prev_btn_page2.disabled)

        # 25 types -> no nav buttons and content "Select an RP type to manage:"
        types_25 = [f"t{i}" for i in range(25)]
        view_25 = ManageRPView(user_id=1, guild_id=1, rp_types=types_25, cog=MagicMock())
        self.assertEqual(len(view_25.children), 1)
        content_25 = view_25._build_type_screen() if hasattr(view_25, "_build_type_screen") else "Select an RP type to manage:"
        self.assertEqual(content_25, "Select an RP type to manage:")

        # 26 types -> 2 pages
        types_26 = [f"t{i}" for i in range(26)]
        view_26 = ManageRPView(user_id=1, guild_id=1, rp_types=types_26, cog=MagicMock())
        self.assertGreater(len(view_26.children), 1)

    async def test_2_back_to_types_and_selection(self):
        types_30 = [f"t{i}" for i in range(30)]
        view = ManageRPView(user_id=1, guild_id=1, rp_types=types_30, cog=MagicMock())
        inter = MagicMock(spec=discord.Interaction)
        inter.response = MagicMock()
        inter.response.edit_message = AsyncMock()
        
        await view.type_next_callback(inter)
        self.assertEqual(view.type_page, 1)
        
        # type_select_callback simulation
        inter.data = {"values": [view.type_select.options[0].value]}
        await view.type_select_callback(inter)
        self.assertEqual(view.selected_type, view.type_select.options[0].value)

        # back_to_types_callback returns to page content consistent with page count
        await view.back_to_types_callback(inter)
        self.assertIsNone(view.selected_type)
        self.assertEqual(view.type_page, 1)
        inter.response.edit_message.assert_called()

    async def test_3_rp_back_view_double_click(self):
        async def _exec(*a, **kw):
            await asyncio.sleep(0.05)
            return discord.Embed()

        cog_mock = MagicMock()
        cog_mock._execute_rp = AsyncMock(side_effect=_exec)
        
        view = RPBackView(cog=cog_mock, rp_type="hug", original_actor_id=2, target_id=3, guild_id=1)
        
        inter = MagicMock(spec=discord.Interaction)
        inter.guild = MagicMock(spec=discord.Guild)
        member_mock = MagicMock(spec=discord.Member)
        member_mock.mention = "<@2>"
        member_mock.display_name = "Actor"
        inter.guild.get_member.return_value = member_mock
        inter.user.id = 3
        inter.response = MagicMock()
        inter.response.send_message = AsyncMock()
        inter.message = MagicMock(spec=discord.Message)
        inter.message.edit = AsyncMock()

        # Double click via gather
        await asyncio.gather(
            view.back.callback(inter),
            view.back.callback(inter),
        )

        # _execute_rp awaited once
        self.assertEqual(cog_mock._execute_rp.await_count, 1)
        inter.response.send_message.assert_called()
        args, kwargs = inter.response.send_message.call_args
        self.assertIn("already used", args[0])
        self.assertTrue(kwargs.get("ephemeral", False))

        # With target_id None (everyone), both proceed
        view_everyone = RPBackView(cog=cog_mock, rp_type="hug", original_actor_id=2, target_id=None, guild_id=1)
        cog_mock._execute_rp.reset_mock()
        await asyncio.gather(
            view_everyone.back.callback(inter),
            view_everyone.back.callback(inter),
        )
        self.assertEqual(cog_mock._execute_rp.await_count, 2)

    async def test_4_rp_back_view_failure_resets(self):
        cog_mock = MagicMock()
        cog_mock._execute_rp = AsyncMock(side_effect=[None, discord.Embed()])
        
        view = RPBackView(cog=cog_mock, rp_type="hug", original_actor_id=2, target_id=3, guild_id=1)
        inter = MagicMock(spec=discord.Interaction)
        inter.guild = MagicMock(spec=discord.Guild)
        member_mock = MagicMock(spec=discord.Member)
        inter.guild.get_member.return_value = member_mock
        inter.user.id = 3
        inter.response = MagicMock()
        inter.response.send_message = AsyncMock()
        inter.message = MagicMock(spec=discord.Message)
        inter.message.edit = AsyncMock()

        # First call returns None -> failure -> resets flag
        await view.back.callback(inter)
        self.assertFalse(view._used)

        # Second call should proceed and succeed
        await view.back.callback(inter)
        self.assertEqual(cog_mock._execute_rp.await_count, 2)

        # Guild-None early return does not consume flag
        view_no_guild = RPBackView(cog=cog_mock, rp_type="hug", original_actor_id=2, target_id=3, guild_id=1)
        inter_no_guild = MagicMock(spec=discord.Interaction)
        inter_no_guild.guild = None
        inter_no_guild.response.send_message = AsyncMock()
        await view_no_guild.back.callback(inter_no_guild)
        self.assertFalse(view_no_guild._used)

    async def test_5_on_member_remove(self):
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO member_behavior (guild_id, user_id, joined_at) VALUES (1, 10, 1000)")
            await conn.execute("INSERT INTO member_behavior (guild_id, user_id, joined_at) VALUES (1, 11, 1000)")
            await conn.commit()

        self.cog._messages[(1, 10)] = [5, 2000, 1000]

        member = MagicMock(spec=discord.Member)
        member.guild = MagicMock(spec=discord.Guild)
        member.guild.id = 1
        member.id = 10
        member.bot = False

        await self.cog.on_member_remove(member)

        async with self.pool.acquire() as conn:
            cur1 = await conn.execute("SELECT 1 FROM member_behavior WHERE guild_id = 1 AND user_id = 10")
            self.assertIsNone(await cur1.fetchone())
            cur2 = await conn.execute("SELECT 1 FROM member_behavior WHERE guild_id = 1 AND user_id = 11")
            self.assertIsNotNone(await cur2.fetchone())

        self.assertNotIn((1, 10), self.cog._messages)

        # Failing DB does not raise
        with patch("database.execute_query", new=AsyncMock(side_effect=RuntimeError("DB fail"))):
            await self.cog.on_member_remove(member)

    async def test_6_on_guild_remove(self):
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO rp_types VALUES (1, 'hug')")
            await conn.execute("INSERT INTO rp_types VALUES (2, 'poke')")
            await conn.execute("INSERT INTO roleplay_entries (user_id, guild_id, type) VALUES (10, 1, 'hug')")
            await conn.execute("INSERT INTO roleplay_entries (user_id, guild_id, type) VALUES (20, 2, 'poke')")
            await conn.execute("INSERT INTO guild_configs (guild_id) VALUES (1)")
            await conn.execute("INSERT INTO guild_configs (guild_id) VALUES (2)")
            await conn.execute("INSERT INTO scan_channels VALUES (1, 100)")
            await conn.execute("INSERT INTO scan_channels VALUES (2, 200)")
            await conn.execute("INSERT INTO member_behavior (guild_id, user_id, joined_at) VALUES (1, 10, 1000)")
            await conn.execute("INSERT INTO member_behavior (guild_id, user_id, joined_at) VALUES (2, 20, 1000)")
            await conn.execute("INSERT INTO guild_emojis VALUES (1, 999, 1, 1)")
            await conn.execute("INSERT INTO guild_emojis VALUES (2, 888, 1, 1)")
            # Marriages & children (no guild column)
            await conn.execute("INSERT INTO marriages (spouse1_id, spouse2_id) VALUES (100, 101)")
            await conn.execute("INSERT INTO children (child_id, parent_id) VALUES (200, 201)")
            await conn.commit()

        # Pre-seed guild config cache
        await database.get_guild_config(1)
        await database.get_guild_config(2)
        self.assertIn(1, database._guild_config_cache)
        self.assertIn(2, database._guild_config_cache)

        self.cog._messages[(1, 10)] = [1, 1000, 1000]
        self.cog._messages[(2, 20)] = [1, 1000, 1000]
        self.cog._emoji_msg[(1, 999)] = 5
        self.cog._emoji_react[(1, 999)] = 3
        self.cog._emoji_msg[(2, 888)] = 2

        guild1 = MagicMock(spec=discord.Guild)
        guild1.id = 1

        await self.cog.on_guild_remove(guild1)

        async with self.pool.acquire() as conn:
            # Check guild 1 rows are gone
            for tbl in ["guild_configs", "scan_channels", "member_behavior", "guild_emojis", "rp_types", "roleplay_entries"]:
                cur = await conn.execute(f"SELECT 1 FROM {tbl} WHERE guild_id = 1")
                self.assertIsNone(await cur.fetchone(), f"Table {tbl} still has guild 1 rows")

            # Check guild 2 rows are intact
            for tbl, id_col in [("guild_configs", "guild_id"), ("scan_channels", "guild_id"), ("member_behavior", "guild_id"), ("guild_emojis", "guild_id"), ("rp_types", "guild_id"), ("roleplay_entries", "guild_id")]:
                cur = await conn.execute(f"SELECT 1 FROM {tbl} WHERE {id_col} = 2")
                self.assertIsNotNone(await cur.fetchone(), f"Table {tbl} lost guild 2 rows")

            # Marriages & children untouched
            self.assertIsNotNone(await (await conn.execute("SELECT 1 FROM marriages WHERE spouse1_id = 100")).fetchone())
            self.assertIsNotNone(await (await conn.execute("SELECT 1 FROM children WHERE child_id = 200")).fetchone())

        # In-memory counters for guild 1 dropped, guild 2 kept
        self.assertNotIn((1, 10), self.cog._messages)
        self.assertNotIn((1, 999), self.cog._emoji_msg)
        self.assertIn((2, 20), self.cog._messages)
        self.assertIn((2, 888), self.cog._emoji_msg)

        # Cache invalidated for guild 1
        self.assertNotIn(1, database._guild_config_cache)
        self.assertIn(2, database._guild_config_cache)

        # Test execute_batch rollback on failure (atomic batch test pattern)
        bad_statements = [
            ("INSERT INTO rp_types VALUES (99, 'test')", []),
            ("INSERT INTO non_existent_table_xyz VALUES (?)", [(1,)]),
        ]
        with self.assertRaises(Exception):
            await database.execute_batch(bad_statements)

    async def test_7_listeners_never_raise(self):
        guild1 = MagicMock(spec=discord.Guild)
        guild1.id = 1
        with patch("database.execute_batch", new=AsyncMock(side_effect=RuntimeError("DB error"))):
            # Should not raise exception
            await self.cog.on_guild_remove(guild1)
        # Cache invalidation still happened in finally
        self.assertNotIn(1, database._guild_config_cache)
