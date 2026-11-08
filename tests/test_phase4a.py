import os
import importlib
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from bot import requested_permissions, build_invite_url, OkinerBot
from cogs.behavior import Behavior

class TestPhase4A(unittest.IsolatedAsyncioTestCase):
    def test_sync_uses_send_not_reply(self):
        import main
        with open(main.__file__, "r", encoding="utf-8") as f:
            main_text = f.read()
        self.assertNotIn("ctx.reply(", main_text)
        self.assertIn("ctx.send(", main_text)
        self.assertEqual(main_text.count("ctx.send("), 5)

    async def test_sync_command_sends_without_reply(self):
        os.environ["DISCORD_TOKEN"] = "fake_token_for_test"
        import main
        importlib.reload(main)

        ctx = MagicMock()
        ctx.send = AsyncMock()
        ctx.reply = AsyncMock()
        ctx.guild = MagicMock()

        with patch("bot.OkinerTree.sync", new=AsyncMock(return_value=[1, 2])):
            await main.sync.callback(ctx, "global")

        ctx.send.assert_awaited_once()
        ctx.reply.assert_not_awaited()
        args, kwargs = ctx.send.call_args
        self.assertIn("Global sync finished", args[0])

    def test_read_message_history_requested(self):
        self.assertTrue(requested_permissions.read_message_history)
        url = build_invite_url("123456")
        self.assertIn(f"permissions={requested_permissions.value}", url)

    async def test_enableunverification_says_not_active(self):
        bot_mock = MagicMock(spec=OkinerBot)
        cog = Behavior(bot_mock)
        try:
            interaction = MagicMock(spec=discord.Interaction)
            interaction.guild_id = 456
            interaction.response.send_message = AsyncMock()

            # Positive control: fetch_one returns None (no verified role configured)
            with patch("database.fetch_one", new=AsyncMock(return_value=None)), \
                 patch("database.execute_query", new=AsyncMock()) as mock_exec:
                await cog.enableunverification.callback(cog, interaction)
                interaction.response.send_message.assert_awaited_once_with(
                    "Please configure a verified role first using `/crouton setup`.", ephemeral=True
                )
                mock_exec.assert_not_awaited()

            # Normal path: fetch_one returns verified role id
            interaction.response.send_message.reset_mock()
            mock_exec = AsyncMock()
            mock_invalidate = MagicMock()
            with patch("database.fetch_one", new=AsyncMock(return_value=(789,))), \
                 patch("database.execute_query", new=mock_exec), \
                 patch("database.invalidate_guild_config", mock_invalidate):
                await cog.enableunverification.callback(cog, interaction)
                mock_exec.assert_awaited_once()
                mock_invalidate.assert_called_once_with(456)
                interaction.response.send_message.assert_awaited_once()
                call_args = interaction.response.send_message.call_args
                self.assertIn("not active yet", call_args[0][0])
                self.assertTrue(call_args[1].get("ephemeral"))
        finally:
            await cog.cog_unload()

    def test_gitignore_rules(self):
        gitignore_path = os.path.join(os.path.dirname(__file__), "..", ".gitignore")
        with open(gitignore_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        self.assertNotIn("*.sqlite3-query", content)
        
        lines = content.splitlines()
        required = [
            "*.db-journal",
            "*.sqlite3",
            "rp.db.bak-*",
            "*.log",
            ".idea/",
            ".vscode/",
            "venv/",
            ".pytest_cache/",
        ]
        for req in required:
            self.assertEqual(lines.count(req), 1, f"Required line {req!r} count in lines is not 1")

        self.assertTrue(content.endswith("\n"))
        self.assertFalse(content.endswith("\n\n"))

if __name__ == "__main__":
    unittest.main()
