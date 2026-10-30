import tempfile
import pathlib
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asqlite
import discord
from discord.ext import commands

import migrations
import database
from database import GuildConfig, get_guild_config, invalidate_guild_config, init_connection, set_bot
from cogs.moderation import Moderation
from cogs.behavior import Behavior


class StubBot:
    def __init__(self, db_pool):
        self.db_pool = db_pool
        self.wait_until_ready = AsyncMock()


class TestGuildConfigCache(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        database._guild_config_cache.clear()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "config.db")
        schema_path = pathlib.Path(__file__).resolve().parent.parent / "rp_schema.sql"
        self.schema_sql = schema_path.read_text(encoding="utf-8")
        migrations.run_migrations(self.db_path, self.schema_sql)
        self.pool = await asqlite.create_pool(self.db_path, size=1, init=init_connection)
        self.stub_bot = StubBot(self.pool)
        set_bot(self.stub_bot)

    async def asyncTearDown(self):
        await self.pool.close()
        self.temp_dir.cleanup()
        database._guild_config_cache.clear()

    async def test_miss_then_hit_uses_cache(self):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO guild_configs (guild_id, log_channel_id, honeypot_channel_id, verified_role_id, moderator_role_id, inactivity_system_enabled) VALUES (?, ?, ?, ?, ?, ?)",
                (1, 10, 20, 30, 40, 1)
            )
            await conn.commit()

        cfg1 = await get_guild_config(1)
        self.assertEqual(cfg1.guild_id, 1)
        self.assertEqual(cfg1.log_channel_id, 10)
        self.assertEqual(cfg1.honeypot_channel_id, 20)
        self.assertEqual(cfg1.verified_role_id, 30)
        self.assertEqual(cfg1.moderator_role_id, 40)
        self.assertTrue(cfg1.inactivity_system_enabled)

        # Modify row directly via raw sqlite3 to test caching (stale return)
        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE guild_configs SET honeypot_channel_id = 21 WHERE guild_id = 1")
            await conn.commit()

        cfg_cached = await get_guild_config(1)
        self.assertEqual(cfg_cached.honeypot_channel_id, 20)  # stale due to cache

        invalidate_guild_config(1)
        cfg_refreshed = await get_guild_config(1)
        self.assertEqual(cfg_refreshed.honeypot_channel_id, 21)

    async def test_none_is_cached(self):
        cfg = await get_guild_config(2)
        self.assertIsNone(cfg)
        self.assertIn(2, database._guild_config_cache)
        self.assertIsNone(database._guild_config_cache[2])

        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO guild_configs (guild_id, honeypot_channel_id) VALUES (?, ?)",
                (2, 50)
            )
            await conn.commit()

        # Still returns None because None is cached
        cfg_cached = await get_guild_config(2)
        self.assertIsNone(cfg_cached)

        invalidate_guild_config(2)
        cfg_refreshed = await get_guild_config(2)
        self.assertEqual(cfg_refreshed.honeypot_channel_id, 50)

    async def test_invalidate_only_affects_that_guild(self):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO guild_configs (guild_id, honeypot_channel_id) VALUES (1, 100), (3, 300)"
            )
            await conn.commit()

        await get_guild_config(1)
        await get_guild_config(3)

        async with self.pool.acquire() as conn:
            await conn.execute("UPDATE guild_configs SET honeypot_channel_id = 101 WHERE guild_id = 1")
            await conn.execute("UPDATE guild_configs SET honeypot_channel_id = 301 WHERE guild_id = 3")
            await conn.commit()

        invalidate_guild_config(1)

        # Guild 1 should refresh, Guild 3 should remain cached (stale 300)
        self.assertEqual((await get_guild_config(1)).honeypot_channel_id, 101)
        self.assertEqual((await get_guild_config(3)).honeypot_channel_id, 300)

    async def test_dataclass_frozen(self):
        cfg = GuildConfig(guild_id=1, log_channel_id=None, honeypot_channel_id=None, verified_role_id=None, moderator_role_id=None, inactivity_system_enabled=False)
        with self.assertRaises(Exception): # FrozenInstanceError
            cfg.guild_id = 2

    async def test_writer_order_sethoneypot_set(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 123
        interaction.guild = MagicMock()
        interaction.guild.me.guild_permissions = discord.Permissions(ban_members=True)
        interaction.response.send_message = AsyncMock()
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 999
        channel.mention = "<#999>"

        call_order = []
        async def mock_exec(*args, **kwargs):
            call_order.append("exec")

        def mock_invalidate(guild_id):
            call_order.append("invalidate")
            self.assertEqual(guild_id, 123)

        with patch("database.fetch_one", new=AsyncMock(return_value=None)), \
             patch("database.execute_query", new=AsyncMock(side_effect=mock_exec)), \
             patch("database.invalidate_guild_config", side_effect=mock_invalidate):
            await cog.sethoneypot.callback(cog, interaction, channel)

        self.assertEqual(call_order, ["exec", "invalidate"])

    async def test_writer_order_sethoneypot_clear(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 123
        interaction.response.send_message = AsyncMock()

        call_order = []
        async def mock_exec(*args, **kwargs):
            call_order.append("exec")

        def mock_invalidate(guild_id):
            call_order.append("invalidate")
            self.assertEqual(guild_id, 123)

        with patch("database.fetch_one", new=AsyncMock()), \
             patch("database.execute_query", new=AsyncMock(side_effect=mock_exec)), \
             patch("database.invalidate_guild_config", side_effect=mock_invalidate):
            await cog.sethoneypot.callback(cog, interaction, None)

        self.assertEqual(call_order, ["exec", "invalidate"])

    async def test_writer_order_crouton_setup(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 123
        interaction.response.send_message = AsyncMock()

        call_order = []
        async def mock_exec(*args, **kwargs):
            call_order.append("exec")

        def mock_invalidate(guild_id):
            call_order.append("invalidate")
            self.assertEqual(guild_id, 123)

        with patch("database.fetch_one", new=AsyncMock(return_value=(None, None, None, None, 0))), \
             patch("database.execute_query", new=AsyncMock(side_effect=mock_exec)), \
             patch("database.invalidate_guild_config", side_effect=mock_invalidate):
            await cog.crouton_setup.callback(cog, interaction)

        self.assertEqual(call_order, ["exec", "invalidate"])

    async def test_writer_order_enableunverification(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Behavior(bot)
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 123
        interaction.response.send_message = AsyncMock()

        call_order = []
        async def mock_exec(*args, **kwargs):
            call_order.append("exec")

        def mock_invalidate(guild_id):
            call_order.append("invalidate")
            self.assertEqual(guild_id, 123)

        with patch("database.fetch_one", new=AsyncMock(return_value=(30,))), \
             patch("database.execute_query", new=AsyncMock(side_effect=mock_exec)), \
             patch("database.invalidate_guild_config", side_effect=mock_invalidate):
            await cog.enableunverification.callback(cog, interaction)

        self.assertEqual(call_order, ["exec", "invalidate"])

    async def test_writer_order_disableunverification(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Behavior(bot)
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 123
        interaction.response.send_message = AsyncMock()

        call_order = []
        async def mock_exec(*args, **kwargs):
            call_order.append("exec")

        def mock_invalidate(guild_id):
            call_order.append("invalidate")
            self.assertEqual(guild_id, 123)

        with patch("database.execute_query", new=AsyncMock(side_effect=mock_exec)), \
             patch("database.invalidate_guild_config", side_effect=mock_invalidate):
            await cog.disableunverification.callback(cog, interaction)

        self.assertEqual(call_order, ["exec", "invalidate"])

    async def test_sethoneypot_end_to_end_cache_refresh(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 10
        interaction.guild = MagicMock()
        interaction.guild.me.guild_permissions = discord.Permissions(ban_members=True)
        interaction.response.send_message = AsyncMock()

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 888
        channel.mention = "<#888>"

        await cog.sethoneypot.callback(cog, interaction, channel)
        cfg = await get_guild_config(10)
        self.assertEqual(cfg.honeypot_channel_id, 888)

        # Clear honeypot
        await cog.sethoneypot.callback(cog, interaction, None)
        cfg_cleared = await get_guild_config(10)
        self.assertIsNone(cfg_cleared.honeypot_channel_id)

    async def test_listener_uses_cache_not_db(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)

        message = MagicMock(spec=discord.Message)
        message.author = MagicMock(spec=discord.Member)
        message.author.bot = False
        message.guild = MagicMock(spec=discord.Guild)
        message.guild.id = 1000

        with patch("database.fetch_one", new=AsyncMock(side_effect=AssertionError("Should not query DB fetch_one"))), \
             patch("database.get_guild_config", new=AsyncMock(return_value=None)):
            await cog.on_message(message)


if __name__ == "__main__":
    unittest.main()
