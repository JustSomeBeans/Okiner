import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from discord import app_commands
import asyncio
import sqlite3
import tempfile
import pathlib
import os
import asqlite

import migrations
from database import init_connection, set_bot
from cogs.family_commands import FamilyCommands
from views import MarriageConfirmView, AdoptionConfirmView, MarriageContainer, AdoptContainer

class TestProposals(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "rp.db")
        schema_path = pathlib.Path(__file__).resolve().parent.parent / "rp_schema.sql"
        self.schema_sql = schema_path.read_text(encoding="utf-8")
        migrations.run_migrations(self.db_path, self.schema_sql)
        self.pool = await asqlite.create_pool(self.db_path, size=1, init=init_connection)
        set_bot(MagicMock(db_pool=self.pool))
        self.bot = MagicMock()
        self.cog = FamilyCommands(self.bot)

    async def asyncTearDown(self):
        await self.pool.close()
        self.temp_dir.cleanup()

    def _make_interaction(self, user_id=20, guild_id=100):
        i = MagicMock(spec=discord.Interaction)
        i.user.id = user_id
        i.guild_id = guild_id
        i.response = MagicMock()
        i.response.send_message = AsyncMock()
        i.response.edit_message = AsyncMock()
        i.response.is_done.return_value = False
        i.followup = MagicMock()
        i.followup.send = AsyncMock()
        return i

    async def test_1_cooldown(self):
        marry_check = None
        for check in self.cog.marry.checks:
            if hasattr(check, "__name__") and "predicate" in check.__name__:
                marry_check = check
                break
        adopt_check = None
        for check in self.cog.adopt.checks:
            if hasattr(check, "__name__") and "predicate" in check.__name__:
                adopt_check = check
                break

        self.assertIsNotNone(marry_check)
        self.assertIsNotNone(adopt_check)

        for check_func in [marry_check, adopt_check]:
            with self.subTest(check=check_func):
                i1 = self._make_interaction(user_id=5, guild_id=1)
                i1.created_at = discord.utils.utcnow()

                res1 = await check_func(i1)
                self.assertTrue(res1)

                i2 = self._make_interaction(user_id=5, guild_id=1)
                i2.created_at = discord.utils.utcnow()
                with self.assertRaises(app_commands.CommandOnCooldown):
                    await check_func(i2)

                i3 = self._make_interaction(user_id=6, guild_id=1)
                i3.created_at = discord.utils.utcnow()
                self.assertTrue(await check_func(i3))

                i4 = self._make_interaction(user_id=5, guild_id=2)
                i4.created_at = discord.utils.utcnow()
                self.assertTrue(await check_func(i4))

    async def test_2_option_types(self):
        for cmd_name, is_member in [("marry", True), ("adopt", True), ("divorce", False), ("disown", False)]:
            cmd = getattr(self.cog, cmd_name)
            ann = cmd.callback.__annotations__.get("user")
            if is_member:
                self.assertEqual(ann, discord.Member)
            else:
                self.assertEqual(ann, discord.User)

    async def test_3_pending_set_blocks_duplicates(self):
        for cmd_method, cmd_name in [(self.cog.marry.callback, "marry"), (self.cog.adopt.callback, "adopt")]:
            with self.subTest(cmd=cmd_name):
                self.cog._pending_proposals.clear()
                interaction = self._make_interaction(user_id=10, guild_id=100)
                target = MagicMock(spec=discord.Member)
                target.id = 20
                target.bot = False
                target.display_name = "Target"

                with patch("cogs.family_commands.fetch_one", new=AsyncMock(return_value=None)):
                    await cmd_method(self.cog, interaction, target)
                    interaction.response.send_message.assert_awaited()
                    self.assertIn((cmd_name, 10, 20), self.cog._pending_proposals)

                    interaction.response.send_message.reset_mock()
                    await cmd_method(self.cog, interaction, target)
                    interaction.response.send_message.assert_awaited_once()
                    args, kwargs = interaction.response.send_message.call_args
                    content = kwargs.get("content") or (args[0] if args else "")
                    self.assertTrue(kwargs.get("ephemeral"))
                    self.assertIn("You already have a pending proposal", content)

    async def test_4_different_kind_or_target_not_blocked(self):
        self.cog._pending_proposals.clear()
        i = self._make_interaction(user_id=10, guild_id=100)
        targetA = MagicMock(spec=discord.Member, id=20, bot=False, display_name="A")
        targetB = MagicMock(spec=discord.Member, id=30, bot=False, display_name="B")

        with patch("cogs.family_commands.fetch_one", new=AsyncMock(return_value=None)):
            await self.cog.marry.callback(self.cog, i, targetA)
            self.assertIn(("marry", 10, 20), self.cog._pending_proposals)

            await self.cog.marry.callback(self.cog, i, targetB)
            self.assertIn(("marry", 10, 30), self.cog._pending_proposals)

            await self.cog.adopt.callback(self.cog, i, targetA)
            self.assertIn(("adopt", 10, 20), self.cog._pending_proposals)

    async def test_5_early_exit_release(self):
        self.cog._pending_proposals.clear()
        i = self._make_interaction(user_id=10, guild_id=100)
        target = MagicMock(spec=discord.Member, id=20, bot=False, display_name="A")

        with patch("cogs.family_commands.fetch_one", new=AsyncMock(return_value=(1,))):
            await self.cog.marry.callback(self.cog, i, target)
            self.assertEqual(len(self.cog._pending_proposals), 0)

        i.response.send_message = AsyncMock(side_effect=Exception("Discord API error"))
        with patch("cogs.family_commands.fetch_one", new=AsyncMock(return_value=None)):
            with self.assertRaises(Exception):
                await self.cog.marry.callback(self.cog, i, target)
            self.assertEqual(len(self.cog._pending_proposals), 0)

    async def test_6_release_on_accept_reject_timeout(self):
        for view_cls, add_func_name in [(MarriageConfirmView, "add_marriage"), (AdoptionConfirmView, "add_child")]:
            with self.subTest(view_cls=view_cls.__name__):
                interaction = self._make_interaction(user_id=20, guild_id=100)
                target = MagicMock(spec=discord.User, id=20, bot=False)
                target.mention = "@target"
                on_done = MagicMock()

                view = view_cls(interaction, target, on_done=on_done)
                container = view.container

                with patch(f"views.{add_func_name}", new=AsyncMock()):
                    await container.accept_callback(interaction)
                on_done.assert_called_once()
                on_done.reset_mock()

                view2 = view_cls(interaction, target, on_done=on_done)
                await view2.container.reject_callback(interaction)
                on_done.assert_called_once()
                on_done.reset_mock()

                view3 = view_cls(interaction, target, on_done=on_done)
                view3.interaction.edit_original_response = AsyncMock()
                view3.interaction.followup.send = AsyncMock()
                await view3.on_timeout()
                on_done.assert_called_once()

                # Calling _release twice calls on_done once (idempotent)
                on_done.reset_mock()
                view3._release()
                view3._release()
                on_done.assert_not_called()

    async def test_7_double_click(self):
        for view_cls, container_cls, add_func_name in [(MarriageConfirmView, MarriageContainer, "add_marriage"), (AdoptionConfirmView, AdoptContainer, "add_child")]:
            with self.subTest(container_cls=container_cls.__name__):
                interaction = self._make_interaction(user_id=20, guild_id=100)
                orig_i = self._make_interaction(user_id=10, guild_id=100)

                view = view_cls(orig_i, MagicMock(bot=False))
                container = view.container

                async def slow_add(*args, **kwargs):
                    await asyncio.sleep(0.02)

                with patch(f"views.{add_func_name}", new=slow_add):
                    await asyncio.gather(
                        container.accept_callback(interaction),
                        container.accept_callback(interaction)
                    )
                interaction.response.send_message.assert_awaited()
                args, kwargs = interaction.response.send_message.call_args
                content = kwargs.get("content") or (args[0] if args else "")
                self.assertEqual(content, "This proposal was already answered.")
                self.assertTrue(kwargs.get("ephemeral"))

                interaction.followup.send.reset_mock()
                view_r = view_cls(orig_i, MagicMock(bot=False))
                container_r = view_r.container
                await asyncio.gather(
                    container_r.reject_callback(interaction),
                    container_r.reject_callback(interaction)
                )
                self.assertEqual(interaction.followup.send.call_count, 1)

    async def test_8_failure_allows_retry(self):
        for view_cls, container_cls, add_func_name in [(MarriageConfirmView, MarriageContainer, "add_marriage"), (AdoptionConfirmView, AdoptContainer, "add_child")]:
            with self.subTest(container_cls=container_cls.__name__):
                orig_i = self._make_interaction(user_id=10, guild_id=100)
                on_done = MagicMock()
                view = view_cls(orig_i, MagicMock(bot=False), on_done=on_done)
                container = view.container

                interaction = self._make_interaction(user_id=20, guild_id=100)

                with patch(f"views.{add_func_name}", new=AsyncMock(side_effect=sqlite3.IntegrityError)):
                    await container.accept_callback(interaction)
                
                self.assertFalse(view._resolved)
                on_done.assert_not_called()

                with patch(f"views.{add_func_name}", new=AsyncMock()):
                    await container.accept_callback(interaction)
                self.assertTrue(view._resolved)
                on_done.assert_called_once()

    async def test_9_mentions(self):
        for view_cls, container_cls, add_func_name in [(MarriageConfirmView, MarriageContainer, "add_marriage"), (AdoptionConfirmView, AdoptContainer, "add_child")]:
            with self.subTest(container_cls=container_cls.__name__):
                orig_i = self._make_interaction(user_id=10, guild_id=100)
                target = MagicMock(spec=discord.User, id=20, bot=False)
                target.mention = "@target"

                view = view_cls(orig_i, target)
                container = view.container

                interaction = self._make_interaction(user_id=20, guild_id=100)

                with patch(f"views.{add_func_name}", new=AsyncMock()):
                    await container.accept_callback(interaction)
                
                _, kwargs = interaction.followup.send.call_args
                am = kwargs.get("allowed_mentions")
                self.assertIsNotNone(am)
                self.assertEqual(set(am.users), {interaction.user, orig_i.user})

                view_r = view_cls(orig_i, target)
                container_r = view_r.container
                await container_r.reject_callback(interaction)
                _, kwargs_r = interaction.followup.send.call_args
                am_r = kwargs_r.get("allowed_mentions")
                self.assertEqual(set(am_r.users), {interaction.user, orig_i.user})

                view_t = view_cls(orig_i, target)
                view_t.interaction.edit_original_response = AsyncMock()
                view_t.interaction.followup.send = AsyncMock()
                await view_t.on_timeout()
                _, kwargs_t = view_t.interaction.followup.send.call_args
                am_t = kwargs_t.get("allowed_mentions")
                self.assertEqual(set(am_t.users), {target})

        self.cog._pending_proposals.clear()
        i = self._make_interaction(user_id=10, guild_id=100)
        t = MagicMock(spec=discord.Member, id=20, bot=False, display_name="Target")
        with patch("cogs.family_commands.fetch_one", new=AsyncMock(return_value=None)):
            await self.cog.marry.callback(self.cog, i, t)
            _, kwargs = i.response.send_message.call_args
            am = kwargs.get("allowed_mentions")
            self.assertEqual(set(am.users), {t})

    async def test_10_timeout_wrapper(self):
        for view_cls in [MarriageConfirmView, AdoptionConfirmView]:
            with self.subTest(view_cls=view_cls.__name__):
                i = self._make_interaction(user_id=20, guild_id=100)
                i.edit_original_response = AsyncMock(side_effect=discord.NotFound(MagicMock(), "Not found"))
                i.followup.send = AsyncMock()
                on_done = MagicMock()

                view = view_cls(i, MagicMock(bot=False), on_done=on_done)
                await view.on_timeout()

                i.edit_original_response.assert_awaited_once()
                i.followup.send.assert_awaited_once()
                on_done.assert_called_once()

if __name__ == "__main__":
    unittest.main()
