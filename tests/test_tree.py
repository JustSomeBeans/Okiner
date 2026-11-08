import unittest
from unittest.mock import AsyncMock, MagicMock
import discord
from discord import app_commands
from bot import OkinerTree, OkinerBot

class TestOkinerTree(unittest.IsolatedAsyncioTestCase):
    def test_okiner_bot_wiring(self):
        bot = OkinerBot()
        self.assertIsInstance(bot.tree, OkinerTree)

    async def test_interaction_check_guild_none_app_command(self):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = None
        interaction.type = discord.InteractionType.application_command
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()

        result = await OkinerTree.interaction_check(None, interaction)
        self.assertFalse(result)
        interaction.response.send_message.assert_awaited_once_with(
            "This command only works in a server.", ephemeral=True
        )

    async def test_interaction_check_guild_none_autocomplete(self):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = None
        interaction.type = discord.InteractionType.autocomplete
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        interaction.followup.send = AsyncMock()

        result = await OkinerTree.interaction_check(None, interaction)
        self.assertFalse(result)
        interaction.response.send_message.assert_not_awaited()
        interaction.followup.send.assert_not_awaited()

    async def test_interaction_check_guild_present(self):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild = MagicMock()
        interaction.response.send_message = AsyncMock()

        result = await OkinerTree.interaction_check(None, interaction)
        self.assertTrue(result)
        interaction.response.send_message.assert_not_awaited()

    async def test_on_error_mappings(self):
        cases = [
            (app_commands.MissingPermissions([]), "You don't have permission to do that."),
            (app_commands.BotMissingPermissions([]), "I'm missing permissions I need for that."),
            (app_commands.NoPrivateMessage(), "This command only works in a server."),
            (app_commands.CommandOnCooldown(MagicMock(), 5.6), "Slow down. Try again in 6s."),
            (app_commands.CheckFailure(), "You can't use that command here."),
        ]

        for error_exc, expected_msg in cases:
            with self.subTest(exc=type(error_exc)):
                interaction = MagicMock(spec=discord.Interaction)
                interaction.response.is_done.return_value = False
                interaction.response.send_message = AsyncMock()

                await OkinerTree.on_error(None, interaction, error_exc)
                interaction.response.send_message.assert_awaited_once_with(expected_msg, ephemeral=True)

    async def test_on_error_followup_if_done(self):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.is_done.return_value = True
        interaction.response.send_message = AsyncMock()
        interaction.followup.send = AsyncMock()

        await OkinerTree.on_error(None, interaction, app_commands.MissingPermissions([]))
        interaction.response.send_message.assert_not_awaited()
        interaction.followup.send.assert_awaited_once_with("You don't have permission to do that.", ephemeral=True)

    async def test_on_error_unwraps_invoke_error_and_hides_secrets(self):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock()
        interaction.command = MagicMock()
        interaction.command.qualified_name = "test_cmd"

        original_exc = ValueError("secret-detail-token-12345")
        invoke_err = app_commands.CommandInvokeError(interaction.command, original_exc)

        with self.assertLogs(level="ERROR") as cm:
            await OkinerTree.on_error(None, interaction, invoke_err)

        interaction.response.send_message.assert_awaited_once()
        msg = interaction.response.send_message.call_args[0][0]
        self.assertEqual(msg, "Something went wrong. Please try again later.")
        self.assertNotIn("secret-detail-token-12345", msg)
        self.assertTrue(any("Unhandled application command error" in log for log in cm.output))

    async def test_on_error_http_exception_handled(self):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.is_done.return_value = False
        interaction.response.send_message = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "API Error"))

        # Should not raise
        await OkinerTree.on_error(None, interaction, app_commands.MissingPermissions([]))

if __name__ == "__main__":
    unittest.main()
