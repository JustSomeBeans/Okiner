import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from discord.ext import commands
from database import GuildConfig
from cogs.moderation import Moderation, is_honeypot_exempt, channel_matches_honeypot

class TestHoneypot(unittest.IsolatedAsyncioTestCase):
    def test_is_honeypot_exempt(self):
        guild = MagicMock(spec=discord.Guild)
        guild.owner_id = 123

        # Owner
        owner = MagicMock(spec=discord.Member)
        owner.id = 123
        owner.guild = guild
        owner.guild_permissions = discord.Permissions.none()
        owner.roles = []
        self.assertTrue(is_honeypot_exempt(owner, 999))

        # Administrator
        admin = MagicMock(spec=discord.Member)
        admin.id = 456
        admin.guild = guild
        admin.guild_permissions = discord.Permissions(administrator=True)
        admin.roles = []
        self.assertTrue(is_honeypot_exempt(admin, 999))

        # Manage Guild
        mg = MagicMock(spec=discord.Member)
        mg.id = 456
        mg.guild = guild
        mg.guild_permissions = discord.Permissions(manage_guild=True)
        mg.roles = []
        self.assertTrue(is_honeypot_exempt(mg, 999))

        # Ban Members
        bm = MagicMock(spec=discord.Member)
        bm.id = 456
        bm.guild = guild
        bm.guild_permissions = discord.Permissions(ban_members=True)
        bm.roles = []
        self.assertTrue(is_honeypot_exempt(bm, 999))

        # Kick Members
        km = MagicMock(spec=discord.Member)
        km.id = 456
        km.guild = guild
        km.guild_permissions = discord.Permissions(kick_members=True)
        km.roles = []
        self.assertTrue(is_honeypot_exempt(km, 999))

        # Manage Messages
        mm = MagicMock(spec=discord.Member)
        mm.id = 456
        mm.guild = guild
        mm.guild_permissions = discord.Permissions(manage_messages=True)
        mm.roles = []
        self.assertTrue(is_honeypot_exempt(mm, 999))

        # Mod Role
        mod_role = MagicMock(spec=discord.Role)
        mod_role.id = 999
        mod_member = MagicMock(spec=discord.Member)
        mod_member.id = 456
        mod_member.guild = guild
        mod_member.guild_permissions = discord.Permissions.none()
        mod_member.roles = [mod_role]
        self.assertTrue(is_honeypot_exempt(mod_member, 999))

        # Plain member (not exempt)
        plain = MagicMock(spec=discord.Member)
        plain.id = 456
        plain.guild = guild
        plain.guild_permissions = discord.Permissions.none()
        plain.roles = []
        self.assertFalse(is_honeypot_exempt(plain, 999))

    def test_channel_matches_honeypot(self):
        # Direct channel match
        ch1 = MagicMock(spec=discord.TextChannel)
        ch1.id = 111
        self.assertTrue(channel_matches_honeypot(ch1, 111))

        # Thread with matching parent_id
        th = MagicMock(spec=discord.Thread)
        th.id = 222
        th.parent_id = 111
        self.assertTrue(channel_matches_honeypot(th, 111))

        # Unrelated channel
        ch2 = MagicMock(spec=discord.TextChannel)
        ch2.id = 333
        ch2.parent_id = 444
        self.assertFalse(channel_matches_honeypot(ch2, 111))

    async def test_on_message_listener_success(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)

        guild = MagicMock(spec=discord.Guild)
        guild.id = 1000
        guild.owner_id = 1
        guild.me = MagicMock(spec=discord.Member)
        guild.me.guild_permissions = discord.Permissions(ban_members=True)

        author = MagicMock(spec=discord.Member)
        author.id = 2000
        author.bot = False
        author.guild = guild
        author.guild_permissions = discord.Permissions.none()
        author.roles = []
        author.top_role = MagicMock()
        author.top_role.__ge__ = lambda self, other: False
        guild.me.top_role = MagicMock()

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 5000
        channel.mention = "<#5000>"

        message = MagicMock(spec=discord.Message)
        message.guild = guild
        message.author = author
        message.channel = channel
        message.delete = AsyncMock()

        log_chan = MagicMock(spec=discord.TextChannel)
        log_chan.send = AsyncMock()
        guild.get_channel.return_value = log_chan
        guild.ban = AsyncMock()

        with patch("database.get_guild_config", new=AsyncMock(return_value=GuildConfig(guild_id=1000, log_channel_id=6000, honeypot_channel_id=5000, verified_role_id=None, moderator_role_id=999, inactivity_system_enabled=False))) as mock_fetch:
            await cog.on_message(message)
            mock_fetch.assert_awaited_once()
            guild.ban.assert_awaited_once_with(
                author,
                reason="Triggered honeypot channel",
                delete_message_seconds=3600
            )
            message.delete.assert_not_called()
            log_chan.send.assert_awaited_once()
            embed = log_chan.send.call_args.kwargs["embed"]
            self.assertEqual(embed.color.value, 0xe74c3c)
            self.assertEqual(embed.title, "Honeypot Triggered")

    async def test_on_message_listener_ban_forbidden(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)

        guild = MagicMock(spec=discord.Guild)
        guild.id = 1000
        guild.owner_id = 1
        guild.me = MagicMock(spec=discord.Member)
        guild.me.guild_permissions = discord.Permissions(ban_members=True)

        author = MagicMock(spec=discord.Member)
        author.id = 2000
        author.bot = False
        author.guild = guild
        author.guild_permissions = discord.Permissions.none()
        author.roles = []
        author.top_role = MagicMock()
        author.top_role.__ge__ = lambda self, other: False
        guild.me.top_role = MagicMock()

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 5000
        channel.mention = "<#5000>"

        message = MagicMock(spec=discord.Message)
        message.guild = guild
        message.author = author
        message.channel = channel
        message.delete = AsyncMock()

        log_chan = MagicMock(spec=discord.TextChannel)
        log_chan.send = AsyncMock()
        guild.get_channel.return_value = log_chan
        forbidden_exc = discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "Forbidden")
        guild.ban = AsyncMock(side_effect=forbidden_exc)

        with patch("database.get_guild_config", new=AsyncMock(return_value=GuildConfig(guild_id=1000, log_channel_id=6000, honeypot_channel_id=5000, verified_role_id=None, moderator_role_id=999, inactivity_system_enabled=False))) as mock_fetch:
            with self.assertLogs(level="WARNING") as cm:
                await cog.on_message(message)
            mock_fetch.assert_awaited_once()
            guild.ban.assert_awaited_once()
            message.delete.assert_awaited_once()
            log_chan.send.assert_awaited_once()
            embed = log_chan.send.call_args.kwargs["embed"]
            self.assertEqual(embed.color.value, 0xf1c40f)
            self.assertEqual(embed.title, "Honeypot Triggered (Ban Failed)")
            self.assertIn("Forbidden", embed.description)
            self.assertTrue(any("Failed to ban user 2000" in log for log in cm.output))

    async def test_on_message_listener_hierarchy_failure(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)

        guild = MagicMock(spec=discord.Guild)
        guild.id = 1000
        guild.owner_id = 1
        guild.me = MagicMock(spec=discord.Member)
        guild.me.guild_permissions = discord.Permissions(ban_members=True)

        author = MagicMock(spec=discord.Member)
        author.id = 2000
        author.bot = False
        author.guild = guild
        author.guild_permissions = discord.Permissions.none()
        author.roles = []
        author.top_role = MagicMock()
        guild.me.top_role = MagicMock()
        author.top_role.__ge__ = lambda self, other: True

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 5000
        channel.mention = "<#5000>"

        message = MagicMock(spec=discord.Message)
        message.guild = guild
        message.author = author
        message.channel = channel
        message.delete = AsyncMock()

        log_chan = MagicMock(spec=discord.TextChannel)
        log_chan.send = AsyncMock()
        guild.get_channel.return_value = log_chan
        guild.ban = AsyncMock()

        with patch("database.get_guild_config", new=AsyncMock(return_value=GuildConfig(guild_id=1000, log_channel_id=6000, honeypot_channel_id=5000, verified_role_id=None, moderator_role_id=999, inactivity_system_enabled=False))) as mock_fetch:
            await cog.on_message(message)
            mock_fetch.assert_awaited_once()
            guild.ban.assert_not_called()
            message.delete.assert_awaited_once()
            log_chan.send.assert_awaited_once()
            embed = log_chan.send.call_args.kwargs["embed"]
            self.assertIn("equal or higher role", embed.description)

    async def test_on_message_no_ban_permission(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)

        guild = MagicMock(spec=discord.Guild)
        guild.id = 1000
        guild.owner_id = 1
        guild.me = MagicMock(spec=discord.Member)
        guild.me.guild_permissions = discord.Permissions(ban_members=False)

        author = MagicMock(spec=discord.Member)
        author.id = 2000
        author.bot = False
        author.guild = guild
        author.guild_permissions = discord.Permissions.none()
        author.roles = []

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 5000
        channel.mention = "<#5000>"

        message = MagicMock(spec=discord.Message)
        message.guild = guild
        message.author = author
        message.channel = channel
        message.delete = AsyncMock()

        log_chan = MagicMock(spec=discord.TextChannel)
        log_chan.send = AsyncMock()
        guild.get_channel.return_value = log_chan
        guild.ban = AsyncMock()

        with patch("database.get_guild_config", new=AsyncMock(return_value=GuildConfig(guild_id=1000, log_channel_id=6000, honeypot_channel_id=5000, verified_role_id=None, moderator_role_id=999, inactivity_system_enabled=False))) as mock_fetch:
            await cog.on_message(message)
            mock_fetch.assert_awaited_once()
            guild.ban.assert_not_called()
            message.delete.assert_awaited_once()
            log_chan.send.assert_awaited_once()
            embed = log_chan.send.call_args.kwargs["embed"]
            self.assertIn("ban_members", embed.description)

    async def test_on_message_delete_raising_forbidden(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)

        guild = MagicMock(spec=discord.Guild)
        guild.id = 1000
        guild.owner_id = 1
        guild.me = MagicMock(spec=discord.Member)
        guild.me.guild_permissions = discord.Permissions(ban_members=False)

        author = MagicMock(spec=discord.Member)
        author.id = 2000
        author.bot = False
        author.guild = guild
        author.guild_permissions = discord.Permissions.none()
        author.roles = []

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 5000
        channel.mention = "<#5000>"

        message = MagicMock(spec=discord.Message)
        message.guild = guild
        message.author = author
        message.channel = channel
        forbidden_exc = discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "Forbidden")
        message.delete = AsyncMock(side_effect=forbidden_exc)

        log_chan = MagicMock(spec=discord.TextChannel)
        log_chan.send = AsyncMock()
        guild.get_channel.return_value = log_chan
        guild.ban = AsyncMock()

        with patch("database.get_guild_config", new=AsyncMock(return_value=GuildConfig(guild_id=1000, log_channel_id=6000, honeypot_channel_id=5000, verified_role_id=None, moderator_role_id=999, inactivity_system_enabled=False))) as mock_fetch:
            with self.assertLogs(level="WARNING") as cm:
                await cog.on_message(message)
            mock_fetch.assert_awaited_once()
            message.delete.assert_awaited_once()
            log_chan.send.assert_awaited_once()
            self.assertTrue(any("Failed to delete message" in log for log in cm.output))

    async def test_on_message_log_send_raising_forbidden(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)

        guild = MagicMock(spec=discord.Guild)
        guild.id = 1000
        guild.owner_id = 1
        guild.me = MagicMock(spec=discord.Member)
        guild.me.guild_permissions = discord.Permissions(ban_members=True)

        author = MagicMock(spec=discord.Member)
        author.id = 2000
        author.bot = False
        author.guild = guild
        author.guild_permissions = discord.Permissions.none()
        author.roles = []
        author.top_role = MagicMock()
        author.top_role.__ge__ = lambda self, other: False
        guild.me.top_role = MagicMock()

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 5000
        channel.mention = "<#5000>"

        message = MagicMock(spec=discord.Message)
        message.guild = guild
        message.author = author
        message.channel = channel

        log_chan = MagicMock(spec=discord.TextChannel)
        forbidden_exc = discord.Forbidden(MagicMock(status=403, reason="Forbidden"), "Forbidden")
        log_chan.send = AsyncMock(side_effect=forbidden_exc)
        guild.get_channel.return_value = log_chan
        guild.ban = AsyncMock()

        with patch("database.get_guild_config", new=AsyncMock(return_value=GuildConfig(guild_id=1000, log_channel_id=6000, honeypot_channel_id=5000, verified_role_id=None, moderator_role_id=999, inactivity_system_enabled=False))) as mock_fetch:
            with self.assertLogs(level="ERROR") as cm:
                await cog.on_message(message)
            mock_fetch.assert_awaited_once()
            guild.ban.assert_awaited_once()
            log_chan.send.assert_awaited_once()
            self.assertTrue(any("Failed to send honeypot log embed" in log for log in cm.output))

    async def test_on_message_listener_dedupe(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)

        guild = MagicMock(spec=discord.Guild)
        guild.id = 1000
        guild.owner_id = 1
        guild.me = MagicMock(spec=discord.Member)
        guild.me.guild_permissions = discord.Permissions(ban_members=True)

        author = MagicMock(spec=discord.Member)
        author.id = 2000
        author.bot = False
        author.guild = guild
        author.guild_permissions = discord.Permissions.none()
        author.roles = []
        author.top_role = MagicMock()
        author.top_role.__ge__ = lambda self, other: False
        guild.me.top_role = MagicMock()

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 5000
        channel.mention = "<#5000>"

        message = MagicMock(spec=discord.Message)
        message.guild = guild
        message.author = author
        message.channel = channel

        log_chan = MagicMock(spec=discord.TextChannel)
        log_chan.send = AsyncMock()
        guild.get_channel.return_value = log_chan
        guild.ban = AsyncMock()

        async def slow_ban(*args, **kwargs):
            await asyncio.sleep(0.05)
        guild.ban.side_effect = slow_ban

        with patch("database.get_guild_config", new=AsyncMock(return_value=GuildConfig(guild_id=1000, log_channel_id=6000, honeypot_channel_id=5000, verified_role_id=None, moderator_role_id=999, inactivity_system_enabled=False))) as mock_fetch:
            await asyncio.gather(
                cog.on_message(message),
                cog.on_message(message)
            )
            mock_fetch.assert_awaited()
            guild.ban.assert_awaited_once()
            log_chan.send.assert_awaited_once()

    async def test_on_message_non_member_author(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)

        message = MagicMock(spec=discord.Message)
        message.author = MagicMock(spec=discord.User)
        message.author.bot = False
        message.guild = MagicMock(spec=discord.Guild)

        with patch("database.get_guild_config", new=AsyncMock()) as mock_fetch:
            await cog.on_message(message)
            mock_fetch.assert_not_awaited()
            message.guild.ban.assert_not_awaited()

    async def test_on_message_exempt_user_and_mod_role(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)

        guild = MagicMock(spec=discord.Guild)
        guild.id = 1000
        log_chan = MagicMock(spec=discord.TextChannel)
        log_chan.send = AsyncMock()
        guild.get_channel.return_value = log_chan
        guild.ban = AsyncMock()

        # Admin user
        author1 = MagicMock(spec=discord.Member)
        author1.bot = False
        author1.guild = guild
        author1.guild_permissions = discord.Permissions(administrator=True)

        message1 = MagicMock(spec=discord.Message)
        message1.guild = guild
        message1.author = author1
        message1.channel = MagicMock(spec=discord.TextChannel)
        message1.channel.id = 5000
        message1.delete = AsyncMock()

        with patch("database.get_guild_config", new=AsyncMock(return_value=GuildConfig(guild_id=1000, log_channel_id=6000, honeypot_channel_id=5000, verified_role_id=None, moderator_role_id=999, inactivity_system_enabled=False))) as mock_fetch:
            await cog.on_message(message1)
            mock_fetch.assert_awaited_once()
            message1.delete.assert_not_awaited()
            guild.ban.assert_not_awaited()
            log_chan.send.assert_not_awaited()

        # User holding configured moderator role id
        mod_role = MagicMock(spec=discord.Role)
        mod_role.id = 999
        author2 = MagicMock(spec=discord.Member)
        author2.bot = False
        author2.guild = guild
        author2.guild_permissions = discord.Permissions.none()
        author2.roles = [mod_role]

        message2 = MagicMock(spec=discord.Message)
        message2.guild = guild
        message2.author = author2
        message2.channel = MagicMock(spec=discord.TextChannel)
        message2.channel.id = 5000
        message2.delete = AsyncMock()

        with patch("database.get_guild_config", new=AsyncMock(return_value=GuildConfig(guild_id=1000, log_channel_id=6000, honeypot_channel_id=5000, verified_role_id=None, moderator_role_id=999, inactivity_system_enabled=False))) as mock_fetch:
            await cog.on_message(message2)
            mock_fetch.assert_awaited_once()
            message2.delete.assert_not_awaited()
            guild.ban.assert_not_awaited()
            log_chan.send.assert_not_awaited()

    async def test_on_message_non_honeypot_channel(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)

        guild = MagicMock(spec=discord.Guild)
        guild.id = 1000
        log_chan = MagicMock(spec=discord.TextChannel)
        log_chan.send = AsyncMock()
        guild.get_channel.return_value = log_chan
        guild.ban = AsyncMock()

        author = MagicMock(spec=discord.Member)
        author.bot = False
        author.guild = guild
        author.guild_permissions = discord.Permissions.none()

        channel = MagicMock(spec=discord.TextChannel)
        channel.id = 7777 # different from honeypot 5000
        channel.parent_id = 8888

        message = MagicMock(spec=discord.Message)
        message.guild = guild
        message.author = author
        message.channel = channel
        message.delete = AsyncMock()

        with patch("database.get_guild_config", new=AsyncMock(return_value=GuildConfig(guild_id=1000, log_channel_id=6000, honeypot_channel_id=5000, verified_role_id=None, moderator_role_id=999, inactivity_system_enabled=False))) as mock_fetch:
            await cog.on_message(message)
            mock_fetch.assert_awaited_once()
            message.delete.assert_not_awaited()
            guild.ban.assert_not_awaited()
            log_chan.send.assert_not_awaited()

    async def test_on_message_fetch_one_none(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)

        guild = MagicMock(spec=discord.Guild)
        guild.id = 1000
        log_chan = MagicMock(spec=discord.TextChannel)
        log_chan.send = AsyncMock()
        guild.get_channel.return_value = log_chan
        guild.ban = AsyncMock()

        author = MagicMock(spec=discord.Member)
        author.bot = False
        author.guild = guild

        message = MagicMock(spec=discord.Message)
        message.guild = guild
        message.author = author
        message.channel = MagicMock(spec=discord.TextChannel)
        message.channel.id = 5000
        message.delete = AsyncMock()

        with patch("database.get_guild_config", new=AsyncMock(return_value=None)) as mock_fetch:
            await cog.on_message(message)
            mock_fetch.assert_awaited_once()
            message.delete.assert_not_awaited()
            guild.ban.assert_not_awaited()
            log_chan.send.assert_not_awaited()

    async def test_on_message_thread_parent_match(self):
        bot = MagicMock(spec=commands.Bot)
        cog = Moderation(bot)

        guild = MagicMock(spec=discord.Guild)
        guild.id = 1000
        guild.owner_id = 1
        guild.me = MagicMock(spec=discord.Member)
        guild.me.guild_permissions = discord.Permissions(ban_members=True)

        author = MagicMock(spec=discord.Member)
        author.id = 2000
        author.bot = False
        author.guild = guild
        author.guild_permissions = discord.Permissions.none()
        author.roles = []
        author.top_role = MagicMock()
        author.top_role.__ge__ = lambda self, other: False
        guild.me.top_role = MagicMock()

        thread = MagicMock(spec=discord.Thread)
        thread.id = 9999
        thread.parent_id = 5000
        thread.mention = "<#9999>"

        message = MagicMock(spec=discord.Message)
        message.guild = guild
        message.author = author
        message.channel = thread

        log_chan = MagicMock(spec=discord.TextChannel)
        log_chan.send = AsyncMock()
        guild.get_channel.return_value = log_chan
        guild.ban = AsyncMock()

        with patch("database.get_guild_config", new=AsyncMock(return_value=GuildConfig(guild_id=1000, log_channel_id=6000, honeypot_channel_id=5000, verified_role_id=None, moderator_role_id=999, inactivity_system_enabled=False))) as mock_fetch:
            await cog.on_message(message)
            mock_fetch.assert_awaited_once()
            guild.ban.assert_awaited_once()
            log_chan.send.assert_awaited_once()

if __name__ == "__main__":
    unittest.main()
