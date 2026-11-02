import tempfile
import pathlib
import os
import sqlite3
import datetime
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asqlite
import discord

import migrations
import database
from database import init_connection, set_bot, GuildConfig
from cogs.behavior import Behavior
from bot import OkinerBot


class StubBot:
    def __init__(self, db_pool):
        self.db_pool = db_pool
        self.wait_until_ready = AsyncMock()


class TestBehaviorBatch(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        database._guild_config_cache.clear()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "behavior.db")
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

    async def test_on_message_does_not_touch_db(self):
        message = MagicMock(spec=discord.Message)
        message.guild = MagicMock(spec=discord.Guild)
        message.guild.id = 1
        message.author = MagicMock(spec=discord.Member)
        message.author.bot = False
        message.author.id = 100
        message.author.joined_at = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
        message.content = "hello"

        with patch("database.execute_query", new=AsyncMock(side_effect=AssertionError("Should not execute_query"))), \
             patch("database.fetch_one", new=AsyncMock(side_effect=AssertionError("Should not fetch_one"))), \
             patch("database.get_guild_config", new=AsyncMock(return_value=None)):
            for _ in range(3):
                await self.cog.on_message(message)

        self.assertEqual(self.cog._messages[(1, 100)][0], 3)

    async def test_flush_writes_aggregated_counts(self):
        dt = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
        ts = int(dt.timestamp())

        msgA = MagicMock(spec=discord.Message)
        msgA.guild = MagicMock(spec=discord.Guild)
        msgA.guild.id = 1
        msgA.author = MagicMock(spec=discord.Member)
        msgA.author.bot = False
        msgA.author.id = 10
        msgA.author.joined_at = dt
        msgA.content = "hi <@123> <:custom:999> <:custom:999> <:other:888>"

        msgB = MagicMock(spec=discord.Message)
        msgB.guild = MagicMock(spec=discord.Guild)
        msgB.guild.id = 1
        msgB.author = MagicMock(spec=discord.Member)
        msgB.author.bot = False
        msgB.author.id = 20
        msgB.author.joined_at = dt
        msgB.content = "no emoji"

        with patch("database.get_guild_config", new=AsyncMock(return_value=None)):
            await self.cog.on_message(msgA)
            await self.cog.on_message(msgA)
            await self.cog.on_message(msgA)
            await self.cog.on_message(msgB)

        payload = MagicMock(spec=discord.RawReactionActionEvent)
        payload.guild_id = 1
        payload.emoji.id = 999
        await self.cog.on_raw_reaction_add(payload)
        await self.cog.on_raw_reaction_add(payload)

        await self.cog.flush()

        self.assertEqual(self.cog._messages, {})
        self.assertEqual(self.cog._emoji_msg, {})
        self.assertEqual(self.cog._emoji_react, {})

        async with self.pool.acquire() as conn:
            cur = await conn.execute("SELECT user_id, total_messages, joined_at FROM member_behavior ORDER BY user_id")
            rows = [tuple(r) for r in await cur.fetchall()]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0], (10, 3, ts))
            self.assertEqual(rows[1], (20, 1, ts))

            cur = await conn.execute("SELECT emoji_id, message_uses, reaction_uses FROM guild_emojis ORDER BY emoji_id")
            erows = [tuple(r) for r in await cur.fetchall()]
            self.assertEqual(len(erows), 2)
            self.assertEqual(erows[0], (888, 3, 0))
            self.assertEqual(erows[1], (999, 6, 2))

    async def test_flush_is_additive_with_existing_rows(self):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO member_behavior (guild_id, user_id, joined_at, total_messages, last_active_at) VALUES (1, 10, 50, 5, 1000)"
            )
            await conn.execute(
                "INSERT INTO guild_emojis (guild_id, emoji_id, message_uses) VALUES (1, 999, 4)"
            )
            await conn.commit()

        self.cog._messages[(1, 10)] = [2, 2000, 50]
        self.cog._emoji_msg[(1, 999)] = 1
        await self.cog.flush()

        async with self.pool.acquire() as conn:
            cur = await conn.execute("SELECT total_messages, joined_at, last_active_at FROM member_behavior WHERE guild_id=1 AND user_id=10")
            row = tuple(await cur.fetchone())
            self.assertEqual(row, (7, 50, 2000))

            cur = await conn.execute("SELECT message_uses FROM guild_emojis WHERE guild_id=1 AND emoji_id=999")
            erow = await cur.fetchone()
            self.assertEqual(erow[0], 5)

    async def test_last_active_never_goes_backwards(self):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO member_behavior (guild_id, user_id, joined_at, total_messages, last_active_at) VALUES (1, 10, 50, 1, 9999999999)"
            )
            await conn.commit()

        self.cog._messages[(1, 10)] = [1, 100, 50]
        await self.cog.flush()

        async with self.pool.acquire() as conn:
            cur = await conn.execute("SELECT last_active_at FROM member_behavior WHERE guild_id=1 AND user_id=10")
            self.assertEqual((await cur.fetchone())[0], 9999999999)

    async def test_flush_empty_is_noop(self):
        with patch("database.execute_batch", new=AsyncMock(side_effect=AssertionError("Should not call execute_batch"))):
            await self.cog.flush()

    async def test_flush_failure_merges_back(self):
        self.cog._messages[(1, 10)] = [3, 100, 50]
        self.cog._emoji_msg[(1, 999)] = 2

        with patch("database.execute_batch", new=AsyncMock(side_effect=sqlite3.OperationalError("db locked"))):
            await self.cog.flush()

        self.assertEqual(self.cog._messages[(1, 10)][0], 3)
        self.assertEqual(self.cog._emoji_msg[(1, 999)], 2)

        # Second flush with real execute_batch should succeed
        await self.cog.flush()
        async with self.pool.acquire() as conn:
            cur = await conn.execute("SELECT total_messages FROM member_behavior WHERE guild_id=1 AND user_id=10")
            self.assertEqual((await cur.fetchone())[0], 3)

    async def test_increment_during_flush_not_lost(self):
        self.cog._messages[(1, 10)] = [1, 100, 50]
        orig_batch = database.execute_batch

        async def slow_batch(statements):
            await asyncio.sleep(0.01)
            async with self.cog._flush_lock:
                entry = self.cog._messages.setdefault((1, 10), [0, 200, 50])
                entry[0] += 1
            await orig_batch(statements)

        with patch("database.execute_batch", new=slow_batch):
            await self.cog.flush()

        await self.cog.flush()

        async with self.pool.acquire() as conn:
            cur = await conn.execute("SELECT total_messages FROM member_behavior WHERE guild_id=1 AND user_id=10")
            self.assertEqual((await cur.fetchone())[0], 2)

    async def test_honeypot_channel_message_skipped(self):
        message = MagicMock(spec=discord.Message)
        message.guild = MagicMock(spec=discord.Guild)
        message.guild.id = 1
        message.author = MagicMock(spec=discord.Member)
        message.author.bot = False
        message.author.id = 100
        message.channel = MagicMock()
        message.channel.id = 500

        cfg = GuildConfig(guild_id=1, log_channel_id=None, honeypot_channel_id=500, verified_role_id=None, moderator_role_id=None, inactivity_system_enabled=False)
        with patch("database.get_guild_config", new=AsyncMock(return_value=cfg)):
            await self.cog.on_message(message)

        self.assertEqual(self.cog._messages, {})

    async def test_batch_is_atomic(self):
        statements = [
            ("INSERT INTO member_behavior (guild_id, user_id, joined_at, total_messages, last_active_at) VALUES (?, ?, ?, ?, ?)", [(1, 10, 50, 1, 100)]),
            ("INSERT INTO nonexistent_table (a) VALUES (?)", [(1,)])
        ]
        with self.assertRaises(sqlite3.OperationalError):
            await database.execute_batch(statements)

        async with self.pool.acquire() as conn:
            cur = await conn.execute("SELECT count(*) FROM member_behavior")
            self.assertEqual((await cur.fetchone())[0], 0)

        await database.execute_batch([
            ("INSERT INTO member_behavior (guild_id, user_id, joined_at, total_messages, last_active_at) VALUES (?, ?, ?, ?, ?)", [(1, 10, 50, 1, 100)])
        ])
        async with self.pool.acquire() as conn:
            cur = await conn.execute("SELECT count(*) FROM member_behavior")
            self.assertEqual((await cur.fetchone())[0], 1)

    async def test_cog_unload_flushes(self):
        self.cog._messages[(1, 10)] = [5, 100, 50]
        await self.cog.cog_unload()

        async with self.pool.acquire() as conn:
            cur = await conn.execute("SELECT total_messages FROM member_behavior WHERE guild_id=1 AND user_id=10")
            self.assertEqual((await cur.fetchone())[0], 5)

    async def test_manualresetinactivity_uses_member_joined_at(self):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 1
        interaction.response.send_message = AsyncMock()

        member = MagicMock(spec=discord.Member)
        member.id = 100
        dt = datetime.datetime(2023, 5, 10, tzinfo=datetime.timezone.utc)
        member.joined_at = dt
        expected_joined = int(dt.timestamp())

        captured_params = None
        async def mock_exec(query, params=()):
            nonlocal captured_params
            captured_params = params

        with patch("database.execute_query", new=mock_exec):
            await self.cog.manualresetinactivity.callback(self.cog, interaction, member)

        self.assertEqual(captured_params[2], expected_joined)

        member.joined_at = None
        with patch("database.execute_query", new=mock_exec):
            await self.cog.manualresetinactivity.callback(self.cog, interaction, member)
        self.assertIsInstance(captured_params[2], int)

    async def test_bot_close_order(self):
        bot = OkinerBot()
        call_order = []

        async def mock_super_close(*args, **kwargs):
            call_order.append("super_close")

        pool_mock = MagicMock()
        async def mock_pool_close():
            call_order.append("pool_close")
        pool_mock.close = mock_pool_close
        bot.db_pool = pool_mock

        with patch("discord.ext.commands.Bot.close", new=mock_super_close):
            await bot.close()

        self.assertEqual(call_order, ["super_close", "pool_close"])


if __name__ == "__main__":
    unittest.main()
