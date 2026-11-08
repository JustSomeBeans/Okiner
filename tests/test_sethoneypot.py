import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from discord.ext import commands
from cogs.moderation import Moderation

class TestSetHoneypot(unittest.IsolatedAsyncioTestCase):
    async def test_sethoneypot_channel_equals_log_channel(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 123
        interaction.response.send_message = AsyncMock()

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 999
        channel.mention = "<#999>"

        with patch("database.fetch_one", new=AsyncMock(return_value=(999,))) as mock_fetch, \
             patch("database.execute_query", new=AsyncMock()) as mock_exec:
            await cog.sethoneypot.callback(cog, interaction, channel)

            mock_fetch.assert_awaited_once()
            mock_exec.assert_not_awaited()
            interaction.response.send_message.assert_awaited_once()
            args, kwargs = interaction.response.send_message.call_args
            self.assertIn("can't be the same", args[0])
            self.assertTrue(kwargs.get("ephemeral"))

    async def test_sethoneypot_no_config_row(self):
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

        with patch("database.fetch_one", new=AsyncMock(return_value=None)) as mock_fetch, \
             patch("database.execute_query", new=AsyncMock()) as mock_exec:
            await cog.sethoneypot.callback(cog, interaction, channel)

            mock_fetch.assert_awaited_once()
            mock_exec.assert_awaited_once()
            interaction.response.send_message.assert_awaited_once()
            args, kwargs = interaction.response.send_message.call_args
            self.assertIn("<#999>", args[0])
            self.assertNotIn("Warning", args[0])
            self.assertTrue(kwargs.get("ephemeral"))

    async def test_sethoneypot_diff_log_channel_lacks_ban(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 123
        interaction.guild = MagicMock()
        interaction.guild.me.guild_permissions = discord.Permissions(ban_members=False)
        interaction.response.send_message = AsyncMock()

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 999
        channel.mention = "<#999>"

        with patch("database.fetch_one", new=AsyncMock(return_value=(888,))) as mock_fetch, \
             patch("database.execute_query", new=AsyncMock()) as mock_exec:
            await cog.sethoneypot.callback(cog, interaction, channel)

            mock_fetch.assert_awaited_once()
            mock_exec.assert_awaited_once()
            interaction.response.send_message.assert_awaited_once()
            args, kwargs = interaction.response.send_message.call_args
            self.assertIn("Ban Members", args[0])
            self.assertTrue(kwargs.get("ephemeral"))

    async def test_sethoneypot_has_ban_permission(self):
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

        with patch("database.fetch_one", new=AsyncMock(return_value=(888,))) as mock_fetch, \
             patch("database.execute_query", new=AsyncMock()) as mock_exec:
            await cog.sethoneypot.callback(cog, interaction, channel)

            mock_fetch.assert_awaited_once()
            mock_exec.assert_awaited_once()
            interaction.response.send_message.assert_awaited_once()
            args, kwargs = interaction.response.send_message.call_args
            self.assertNotIn("Warning", args[0])
            self.assertTrue(kwargs.get("ephemeral"))

    async def test_sethoneypot_channel_none(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 123
        interaction.response.send_message = AsyncMock()

        with patch("database.fetch_one", new=AsyncMock()) as mock_fetch, \
             patch("database.execute_query", new=AsyncMock()) as mock_exec:
            await cog.sethoneypot.callback(cog, interaction, None)

            mock_fetch.assert_not_awaited()
            mock_exec.assert_awaited_once()
            exec_args = mock_exec.call_args[0]
            self.assertIsNone(exec_args[1][1])
            
            interaction.response.send_message.assert_awaited_once()
            args, kwargs = interaction.response.send_message.call_args
            self.assertEqual(args[0], "Honeypot channel cleared.")
            self.assertTrue(kwargs.get("ephemeral"))

    async def test_sethoneypot_send_message_always_once(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)

        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 123
        interaction.guild = MagicMock()
        interaction.guild.me.guild_permissions = discord.Permissions(ban_members=True)
        interaction.response.send_message = AsyncMock()

        with patch("database.fetch_one", new=AsyncMock(return_value=None)), \
             patch("database.execute_query", new=AsyncMock()):
            await cog.sethoneypot.callback(cog, interaction, None)
            interaction.response.send_message.assert_awaited_once()

if __name__ == "__main__":
    unittest.main()
