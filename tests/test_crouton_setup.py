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
from database import init_connection, set_bot, get_guild_config
from cogs.moderation import Moderation


class StubBot:
    def __init__(self, db_pool):
        self.db_pool = db_pool
        self.wait_until_ready = AsyncMock()


class TestCroutonSetup(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        database._guild_config_cache.clear()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "crouton_setup.db")
        schema_path = pathlib.Path(__file__).resolve().parent.parent / "rp_schema.sql"
        self.schema_sql = schema_path.read_text(encoding="utf-8")
        migrations.run_migrations(self.db_path, self.schema_sql)
        self.pool = await asqlite.create_pool(self.db_path, size=5, init=init_connection)
        self.stub_bot = StubBot(self.pool)
        set_bot(self.stub_bot)

    async def asyncTearDown(self):
        await self.pool.close()
        self.temp_dir.cleanup()
        database._guild_config_cache.clear()

    def _make_interaction(self, guild_id=1):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = guild_id
        interaction.guild = MagicMock()
        interaction.guild.me = MagicMock()
        interaction.guild.me.guild_permissions = discord.Permissions(ban_members=True)
        interaction.response.send_message = AsyncMock()
        return interaction

    def _make_channel(self, channel_id=10, perms=None):
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = channel_id
        channel.mention = f"<#{channel_id}>"
        if perms is None:
            perms = discord.Permissions(view_channel=True, send_messages=True, embed_links=True)
        channel.permissions_for = MagicMock(return_value=perms)
        return channel

    def _make_role(self, role_id=30, is_default=False, managed=False):
        role = MagicMock(spec=discord.Role)
        role.id = role_id
        role.is_default = MagicMock(return_value=is_default)
        role.managed = managed
        role.mention = f"<@&{role_id}>"
        return role

    async def test_partial_update_preserves_other_columns(self):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO guild_configs (guild_id, log_channel_id, honeypot_channel_id, verified_role_id, moderator_role_id, inactivity_system_enabled) VALUES (?, ?, ?, ?, ?, ?)",
                (1, 10, 20, 30, 40, 1)
            )
            await conn.commit()

        cog = Moderation(self.stub_bot)
        interaction = self._make_interaction(guild_id=1)
        mod_role = self._make_role(role_id=41)

        await cog.crouton_setup.callback(cog, interaction, moderator_role=mod_role)

        async with self.pool.acquire() as conn:
            cur = await conn.execute("SELECT log_channel_id, honeypot_channel_id, verified_role_id, moderator_role_id, inactivity_system_enabled FROM guild_configs WHERE guild_id = ?", (1,))
            row = await cur.fetchone()
        self.assertEqual(tuple(row), (10, 20, 30, 41, 1))

    async def test_first_time_insert(self):
        cog = Moderation(self.stub_bot)
        interaction = self._make_interaction(guild_id=1)
        log_chan = self._make_channel(10)
        ver_role = self._make_role(30)

        await cog.crouton_setup.callback(cog, interaction, log_channel=log_chan, verified_role=ver_role)

        async with self.pool.acquire() as conn:
            cur = await conn.execute("SELECT log_channel_id, honeypot_channel_id, verified_role_id, moderator_role_id, inactivity_system_enabled FROM guild_configs WHERE guild_id = ?", (1,))
            row = await cur.fetchone()
        self.assertEqual(tuple(row), (10, None, 30, None, 0))

    async def test_no_read_before_write(self):
        cog = Moderation(self.stub_bot)
        interaction = self._make_interaction(guild_id=1)
        mod_role = self._make_role(40)

        write_occurred = False
        orig_fetch_one = database.fetch_one
        orig_execute_query = database.execute_query

        async def tracking_fetch_one(query, params=()):
            if not write_occurred:
                raise AssertionError("Read (fetch_one) occurred before write")
            return await orig_fetch_one(query, params)

        async def tracking_execute_query(query, params=()):
            nonlocal write_occurred
            write_occurred = True
            return await orig_execute_query(query, params)

        with patch("database.fetch_one", side_effect=tracking_fetch_one), \
             patch("database.execute_query", side_effect=tracking_execute_query):
            await cog.crouton_setup.callback(cog, interaction, moderator_role=mod_role)

        async with self.pool.acquire() as conn:
            cur = await conn.execute("SELECT moderator_role_id FROM guild_configs WHERE guild_id = ?", (1,))
            row = await cur.fetchone()
        self.assertEqual(row[0], 40)

    async def test_rejects_everyone_moderator_role(self):
        cog = Moderation(self.stub_bot)
        interaction = self._make_interaction(guild_id=1)
        mod_role = self._make_role(30, is_default=True)

        await cog.crouton_setup.callback(cog, interaction, moderator_role=mod_role)

        interaction.response.send_message.assert_awaited_once()
        args, kwargs = interaction.response.send_message.call_args
        self.assertIn("@everyone", args[0])
        self.assertTrue(kwargs.get("ephemeral"))

        async with self.pool.acquire() as conn:
            cur = await conn.execute("SELECT count(*) FROM guild_configs")
            count = (await cur.fetchone())[0]
        self.assertEqual(count, 0)

    async def test_rejects_everyone_verified_role(self):
        cog = Moderation(self.stub_bot)
        interaction = self._make_interaction(guild_id=1)
        ver_role = self._make_role(30, is_default=True)

        await cog.crouton_setup.callback(cog, interaction, verified_role=ver_role)

        interaction.response.send_message.assert_awaited_once()
        args, kwargs = interaction.response.send_message.call_args
        self.assertIn("@everyone", args[0])
        self.assertTrue(kwargs.get("ephemeral"))

        async with self.pool.acquire() as conn:
            cur = await conn.execute("SELECT count(*) FROM guild_configs")
            count = (await cur.fetchone())[0]
        self.assertEqual(count, 0)

    async def test_rejects_managed_verified_role(self):
        cog = Moderation(self.stub_bot)
        interaction = self._make_interaction(guild_id=1)
        ver_role = self._make_role(30, managed=True)

        await cog.crouton_setup.callback(cog, interaction, verified_role=ver_role)

        interaction.response.send_message.assert_awaited_once()
        args, kwargs = interaction.response.send_message.call_args
        self.assertIn("managed", args[0].lower())
        self.assertTrue(kwargs.get("ephemeral"))

        async with self.pool.acquire() as conn:
            cur = await conn.execute("SELECT count(*) FROM guild_configs")
            count = (await cur.fetchone())[0]
        self.assertEqual(count, 0)

    async def test_managed_moderator_role_allowed(self):
        cog = Moderation(self.stub_bot)
        interaction = self._make_interaction(guild_id=1)
        mod_role = self._make_role(40, managed=True)

        await cog.crouton_setup.callback(cog, interaction, moderator_role=mod_role)

        async with self.pool.acquire() as conn:
            cur = await conn.execute("SELECT moderator_role_id FROM guild_configs WHERE guild_id = ?", (1,))
            row = await cur.fetchone()
        self.assertEqual(row[0], 40)

    async def test_rejects_log_channel_without_permissions(self):
        cog = Moderation(self.stub_bot)
        interaction = self._make_interaction(guild_id=1)
        log_chan = self._make_channel(10, perms=discord.Permissions(view_channel=True))

        await cog.crouton_setup.callback(cog, interaction, log_channel=log_chan)

        interaction.response.send_message.assert_awaited_once()
        args, kwargs = interaction.response.send_message.call_args
        self.assertIn("View Channel", args[0])
        self.assertTrue(kwargs.get("ephemeral"))

        async with self.pool.acquire() as conn:
            cur = await conn.execute("SELECT count(*) FROM guild_configs")
            count = (await cur.fetchone())[0]
        self.assertEqual(count, 0)

    async def test_rejects_log_channel_equal_to_honeypot(self):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO guild_configs (guild_id, honeypot_channel_id) VALUES (?, ?)",
                (1, 20)
            )
            await conn.commit()

        cog = Moderation(self.stub_bot)
        interaction = self._make_interaction(guild_id=1)
        log_chan = self._make_channel(20)

        await cog.crouton_setup.callback(cog, interaction, log_channel=log_chan)

        interaction.response.send_message.assert_awaited_once()
        args, kwargs = interaction.response.send_message.call_args
        self.assertIn("honeypot", args[0].lower())
        self.assertTrue(kwargs.get("ephemeral"))

        async with self.pool.acquire() as conn:
            cur = await conn.execute("SELECT log_channel_id, honeypot_channel_id FROM guild_configs WHERE guild_id = ?", (1,))
            row = await cur.fetchone()
        self.assertIsNone(row[0])
        self.assertEqual(row[1], 20)

    async def test_cache_refreshed_after_setup(self):
        cfg_none = await get_guild_config(1)
        self.assertIsNone(cfg_none)

        cog = Moderation(self.stub_bot)
        interaction = self._make_interaction(guild_id=1)
        log_chan = self._make_channel(10)

        await cog.crouton_setup.callback(cog, interaction, log_channel=log_chan)

        cfg_new = await get_guild_config(1)
        self.assertIsNotNone(cfg_new)
        self.assertEqual(cfg_new.log_channel_id, 10)

    async def test_two_concurrent_setups_do_not_lose_updates(self):
        cog = Moderation(self.stub_bot)
        interaction1 = self._make_interaction(guild_id=1)
        interaction2 = self._make_interaction(guild_id=1)
        log_chan = self._make_channel(10)
        mod_role = self._make_role(40)

        await asyncio.gather(
            cog.crouton_setup.callback(cog, interaction1, log_channel=log_chan),
            cog.crouton_setup.callback(cog, interaction2, moderator_role=mod_role),
        )

        async with self.pool.acquire() as conn:
            cur = await conn.execute("SELECT log_channel_id, moderator_role_id FROM guild_configs WHERE guild_id = ?", (1,))
            row = await cur.fetchone()
        self.assertEqual(tuple(row), (10, 40))

    async def test_confirmation_embed_shows_stored_values(self):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO guild_configs (guild_id, verified_role_id) VALUES (?, ?)",
                (1, 30)
            )
            await conn.commit()

        cog = Moderation(self.stub_bot)
        interaction = self._make_interaction(guild_id=1)
        mod_role = self._make_role(40)

        await cog.crouton_setup.callback(cog, interaction, moderator_role=mod_role)

        interaction.response.send_message.assert_awaited_once()
        _, kwargs = interaction.response.send_message.call_args
        embed = kwargs.get("embed")
        self.assertIsNotNone(embed)
        
        field_values = {f.name: f.value for f in embed.fields}
        self.assertEqual(field_values["Verified Role"], "<@&30>")
        self.assertEqual(field_values["Moderator Role"], "<@&40>")
        self.assertEqual(field_values["Log Channel"], "Not set")


if __name__ == "__main__":
    unittest.main()
