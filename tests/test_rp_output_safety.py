from __future__ import annotations

import tempfile
import pathlib
import os
import unittest
from unittest.mock import AsyncMock, MagicMock
import asqlite
import discord

import migrations
from database import init_connection, set_bot
from utils import PlaceholderTarget, apply_placeholders
from cogs.rp_commands import RPCommands
from views import ManageRPEntriesView
from config import MAX_EMBED_DESCRIPTION_LENGTH

class StubBot:
    def __init__(self, db_pool):
        self.db_pool = db_pool

class TestRPOutputSafety(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "rp.db")
        schema_path = pathlib.Path(__file__).resolve().parent.parent / "rp_schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")
        migrations.run_migrations(self.db_path, schema_sql)
        self.pool = await asqlite.create_pool(self.db_path, size=1, init=init_connection)
        self.bot = StubBot(self.pool)
        set_bot(self.bot)
        self.cog = RPCommands(self.bot)

    async def asyncTearDown(self):
        await self.pool.close()
        self.temp_dir.cleanup()

    def test_single_pass(self):
        actor = MagicMock(spec=discord.abc.User)
        actor.mention = "<@1>"
        actor.display_name = "Actor"
        target = PlaceholderTarget("<@2>", "{user}")
        result = apply_placeholders("{target_name} hugs", actor, target)
        self.assertEqual(result, "{user} hugs")

        target2 = PlaceholderTarget("<@2>", "normal")
        actor2 = MagicMock(spec=discord.abc.User)
        actor2.mention = "<@1>"
        actor2.display_name = "{target}"
        result2 = apply_placeholders("{user_name}", actor2, target2)
        self.assertEqual(result2, "{target}")

    def test_markdown_escaped(self):
        actor = MagicMock(spec=discord.abc.User)
        actor.mention = "<@1>"
        actor.display_name = "[free](https://evil)"
        target = PlaceholderTarget("<@2>", "**bold**")
        result_user = apply_placeholders("{user_name}", actor, target)
        self.assertEqual(result_user, discord.utils.escape_markdown("[free](https://evil)"))

        result_target = apply_placeholders("{target_name}", actor, target)
        self.assertEqual(result_target, discord.utils.escape_markdown("**bold**"))

    def test_mention_in_name_neutralised(self):
        actor = MagicMock(spec=discord.abc.User)
        actor.mention = "<@1>"
        actor.display_name = "@everyone"
        target = PlaceholderTarget("<@2>", "target")
        result = apply_placeholders("{user_name}", actor, target)
        self.assertNotIn("@everyone", result)

    def test_mentions_unchanged(self):
        actor = MagicMock(spec=discord.abc.User)
        actor.mention = "<@1>"
        actor.display_name = "User"
        target = PlaceholderTarget("<@2>", "Target")
        result = apply_placeholders("{user} and {target}", actor, target)
        self.assertEqual(result, "<@1> and <@2>")

    def test_unknown_and_repeated_tags(self):
        actor = MagicMock(spec=discord.abc.User)
        actor.mention = "<@1>"
        actor.display_name = "User"
        target = PlaceholderTarget("<@2>", "Target")
        result = apply_placeholders("{foo} {user} {user}", actor, target)
        self.assertEqual(result, "{foo} <@1> <@1>")

    def test_user_name_prefix_precedence(self):
        actor = MagicMock(spec=discord.abc.User)
        actor.mention = "<@1>"
        actor.display_name = "Actor"
        target = PlaceholderTarget("<@2>", "Target")
        result = apply_placeholders("{user_name}", actor, target)
        self.assertEqual(result, "Actor")

    async def test_action_truncation_keeps_closing_bold(self):
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO rp_types VALUES (1, 'hug')")
            long_action = "a" * 5000
            await conn.execute(
                "INSERT INTO roleplay_entries (user_id, guild_id, type, case_type, action_texts) VALUES (1, 1, 'hug', 'standard', ?)",
                (long_action,)
            )
            await conn.commit()

        interaction = MagicMock(spec=discord.Interaction)
        interaction.guild_id = 1
        interaction.user = MagicMock(spec=discord.abc.User)
        interaction.user.mention = "<@1>"
        interaction.user.display_name = "Actor"
        interaction.response.send_message = AsyncMock()

        target_info = PlaceholderTarget("<@2>", "Target")
        embed = await self.cog._execute_rp(interaction, "hug", target_info, "standard")
        self.assertIsNotNone(embed)
        self.assertLessEqual(len(embed.description), MAX_EMBED_DESCRIPTION_LENGTH)
        self.assertTrue(embed.description.startswith("**"))
        self.assertTrue(embed.description.rstrip().endswith("**"))

    def test_render_content_backticks(self):
        view = ManageRPEntriesView(
            user_id=1,
            guild_id=1,
            rp_type="hug",
            pool="std_text",
            case_type="standard",
            column="texts",
            entries=["a```b", "normal text"],
            cog=MagicMock(),
            parent_view=MagicMock(),
        )
        view.page = 0
        content = view.render_content()
        lines = content.splitlines()
        body = "\n".join(lines[2:-1])
        self.assertNotIn("```", body)
        self.assertIn("'''", body)

        # positive control: entry without backticks unchanged
        view.page = 1
        content2 = view.render_content()
        self.assertIn("normal text", content2)

if __name__ == "__main__":
    unittest.main()
