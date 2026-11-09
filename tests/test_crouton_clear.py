from __future__ import annotations

import os
import pathlib
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import asqlite
import discord
from discord import app_commands

import database
import migrations
from database import get_guild_config, init_connection, set_bot
from cogs.moderation import Moderation


class StubBot:
    def __init__(self, db_pool):
        self.db_pool = db_pool
        self.wait_until_ready = AsyncMock()


class TestCroutonClear(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        database._guild_config_cache.clear()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "crouton_clear.db")
        schema_path = pathlib.Path(__file__).resolve().parent.parent / "rp_schema.sql"
        migrations.run_migrations(self.db_path, schema_path.read_text(encoding="utf-8"))
        self.pool = await asqlite.create_pool(self.db_path, size=5, init=init_connection)
        self.stub_bot = StubBot(self.pool)
        set_bot(self.stub_bot)
        self.cog = Moderation(self.stub_bot)

    async def asyncTearDown(self):
        await self.pool.close()
        self.temp_dir.cleanup()
        database._guild_config_cache.clear()

    def _interaction(self, guild_id=1):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = guild_id
        interaction.response.send_message = AsyncMock()
        return interaction

    async def _insert_config(self, guild_id, log=10, honeypot=20, verified=30, mod=40, inactivity=1):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO guild_configs (guild_id, log_channel_id, honeypot_channel_id, verified_role_id, moderator_role_id, inactivity_system_enabled) VALUES (?, ?, ?, ?, ?, ?)",
                (guild_id, log, honeypot, verified, mod, inactivity),
            )
            await conn.commit()

    async def _row(self, guild_id):
        async with self.pool.acquire() as conn:
            cur = await conn.execute(
                "SELECT log_channel_id, honeypot_channel_id, verified_role_id, moderator_role_id, inactivity_system_enabled FROM guild_configs WHERE guild_id = ?",
                (guild_id,),
            )
            row = await cur.fetchone()
        return tuple(row) if row else None

    async def test_clear_nulls_four_settings_and_keeps_inactivity_flag(self):
        await self._insert_config(1)
        self.assertEqual(await self._row(1), (10, 20, 30, 40, 1))

        await self.cog.crouton_clear.callback(self.cog, self._interaction(1))

        self.assertEqual(await self._row(1), (None, None, None, None, 1))

    async def test_clear_leaves_other_guilds_alone(self):
        await self._insert_config(1)
        await self._insert_config(2, log=11, honeypot=21, verified=31, mod=41, inactivity=0)

        await self.cog.crouton_clear.callback(self.cog, self._interaction(1))

        self.assertEqual(await self._row(1), (None, None, None, None, 1))
        self.assertEqual(await self._row(2), (11, 21, 31, 41, 0))

    async def test_clear_with_no_saved_row_creates_nothing(self):
        interaction = self._interaction(1)

        await self.cog.crouton_clear.callback(self.cog, interaction)

        self.assertIsNone(await self._row(1))
        interaction.response.send_message.assert_awaited_once()
        args, kwargs = interaction.response.send_message.call_args
        self.assertIn("no saved settings", args[0])
        self.assertTrue(kwargs.get("ephemeral"))

    async def test_clear_keeps_scan_channels(self):
        await self._insert_config(1)
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO scan_channels (guild_id, channel_id) VALUES (1, 555), (1, 556), (2, 557)")
            await conn.commit()

        await self.cog.crouton_clear.callback(self.cog, self._interaction(1))

        async with self.pool.acquire() as conn:
            cur = await conn.execute("SELECT count(*) FROM scan_channels WHERE guild_id = 1")
            guild_one = (await cur.fetchone())[0]
            cur = await conn.execute("SELECT count(*) FROM scan_channels")
            total = (await cur.fetchone())[0]
        self.assertEqual(guild_one, 2)
        self.assertEqual(total, 3)

    async def test_clear_invalidates_cache(self):
        await self._insert_config(1)
        before = await get_guild_config(1)
        self.assertEqual(before.log_channel_id, 10)
        self.assertEqual(before.honeypot_channel_id, 20)

        await self.cog.crouton_clear.callback(self.cog, self._interaction(1))

        after = await get_guild_config(1)
        self.assertIsNone(after.log_channel_id)
        self.assertIsNone(after.honeypot_channel_id)
        self.assertIsNone(after.verified_role_id)
        self.assertIsNone(after.moderator_role_id)
        self.assertTrue(after.inactivity_system_enabled)

    async def test_clear_replies_once_ephemeral(self):
        await self._insert_config(1)
        interaction = self._interaction(1)

        await self.cog.crouton_clear.callback(self.cog, interaction)

        interaction.response.send_message.assert_awaited_once()
        args, kwargs = interaction.response.send_message.call_args
        self.assertIn("Cleared", args[0])
        self.assertTrue(kwargs.get("ephemeral"))

    async def test_writer_order_write_then_invalidate(self):
        order = []

        async def fake_write(*args, **kwargs):
            order.append("exec")
            return 1

        def fake_invalidate(guild_id):
            order.append("invalidate")
            self.assertEqual(guild_id, 123)

        with patch("database.execute_write", new=AsyncMock(side_effect=fake_write)), \
             patch("database.invalidate_guild_config", side_effect=fake_invalidate):
            await self.cog.crouton_clear.callback(self.cog, self._interaction(123))

        self.assertEqual(order, ["exec", "invalidate"])

    async def test_failed_write_does_not_claim_success(self):
        interaction = self._interaction(1)

        with patch("database.execute_write", new=AsyncMock(side_effect=RuntimeError("boom"))):
            with self.assertRaises(RuntimeError):
                await self.cog.crouton_clear.callback(self.cog, interaction)

        interaction.response.send_message.assert_not_awaited()

    async def test_setup_works_again_after_clear(self):
        await self._insert_config(1)
        await self.cog.crouton_clear.callback(self.cog, self._interaction(1))

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 10
        channel.mention = "<#10>"
        channel.permissions_for = MagicMock(
            return_value=discord.Permissions(view_channel=True, send_messages=True, embed_links=True)
        )
        setup_interaction = self._interaction(1)
        setup_interaction.guild = MagicMock()

        await self.cog.crouton_setup.callback(self.cog, setup_interaction, log_channel=channel)

        self.assertEqual(await self._row(1), (10, None, None, None, 1))


    async def test_clear_requires_guild(self):
        interaction = self._interaction(guild_id=None)

        await self.cog.crouton_clear.callback(self.cog, interaction)

        interaction.response.send_message.assert_awaited_once()
        args, kwargs = interaction.response.send_message.call_args
        self.assertIn("server", args[0])
        self.assertTrue(kwargs.get("ephemeral"))

    async def test_requires_administrator(self):
        checks = self.cog.crouton_clear.checks
        self.assertTrue(checks)

        admin = self._interaction(1)
        admin.permissions = discord.Permissions(administrator=True)
        for check in checks:
            self.assertTrue(await discord.utils.maybe_coroutine(check, admin))

        non_admin = self._interaction(1)
        non_admin.permissions = discord.Permissions(manage_messages=True)
        with self.assertRaises(app_commands.MissingPermissions):
            for check in checks:
                await discord.utils.maybe_coroutine(check, non_admin)


if __name__ == "__main__":
    unittest.main()
