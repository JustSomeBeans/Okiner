import io
import pathlib
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from cogs.family_commands import FamilyCommands, MAX_TREE_NODES

class TestFamilyTree(unittest.IsolatedAsyncioTestCase):
    def test_privacy_excludes_non_members(self):
        cog = FamilyCommands(MagicMock())
        marriages = [(1, 2), (2, 3)]
        children = [(1, 10)]
        allowed = {1, 2, 10}
        nodes, cm, cc, truncated = cog._build_family_component(1, marriages, children, allowed)
        self.assertEqual(nodes, {1, 2, 10})
        self.assertNotIn(3, nodes)
        self.assertNotIn((2, 3), cm)
        self.assertIn((1, 2), cm)
        self.assertIn((1, 10), cc)
        self.assertFalse(truncated)

    def test_target_always_allowed(self):
        cog = FamilyCommands(MagicMock())
        marriages = [(1, 2)]
        children = []
        allowed = {2}  # target 1 not in allowed initially
        nodes, cm, cc, truncated = cog._build_family_component(1, marriages, children, allowed)
        self.assertIn(1, nodes)
        self.assertIn(2, nodes)
        self.assertIn((1, 2), cm)
        self.assertFalse(truncated)

    def test_cap_nearest_first(self):
        cog = FamilyCommands(MagicMock())
        # Target 0 connected to 1..50 (children), plus far nodes 101..105 connected via 50
        marriages = []
        children = [(0, i) for i in range(1, 51)] + [(50, 101), (101, 102)]
        allowed = {0} | set(range(1, 51)) | {101, 102}
        nodes, cm, cc, truncated = cog._build_family_component(0, marriages, children, allowed)
        self.assertEqual(len(nodes), MAX_TREE_NODES)
        self.assertTrue(truncated)
        self.assertIn(0, nodes)
        # Direct neighbors of 0 (1..39 or similar) should be in nodes
        for i in range(1, 39):
            self.assertIn(i, nodes)

    def test_no_truncation_flag_when_small(self):
        cog = FamilyCommands(MagicMock())
        marriages = [(1, 2)]
        children = []
        allowed = {1, 2}
        _, _, _, truncated = cog._build_family_component(1, marriages, children, allowed)
        self.assertFalse(truncated)

    def test_layout_identical_to_reference(self):
        cog = FamilyCommands(MagicMock())
        # Small graph: target 1, spouse 2, parent 10, child 20
        nodes = {1, 2, 10, 20}
        marriages = [(1, 2)]
        children = [(10, 1), (1, 20)]
        positions = cog._layout_family_tree(1, nodes, marriages, children)
        # Reference positions computed from algorithm
        expected_ref = {
            10: (0.0, 0.0),
            1: (-140.0, 166.0),
            2: (140.0, 166.0),
            20: (0.0, 332.0),
        }
        self.assertEqual(positions, expected_ref)

    def test_render_returns_png(self):
        cog = FamilyCommands(MagicMock())
        names = {1: "TargetUser", 2: "SpouseUser"}
        nodes = {1, 2}
        marriages = [(1, 2)]
        children = []
        output = cog._render_family_tree_image(names, 1, nodes, marriages, children)
        self.assertIsInstance(output, io.BytesIO)
        content = output.getvalue()
        self.assertTrue(content.startswith(b"\x89PNG"))

        # Verify no "Unknown User" in cogs/family_commands.py source
        src_path = pathlib.Path(__file__).resolve().parent.parent / "cogs" / "family_commands.py"
        src_text = src_path.read_text(encoding="utf-8")
        self.assertNotIn("Unknown User", src_text)

    def test_font_fallback_order(self):
        cog = FamilyCommands(MagicMock())
        recorded_names = []

        def mock_truetype(name, size):
            recorded_names.append(name)
            if name == "LiberationSans-Regular.ttf":
                return MagicMock()
            raise OSError("not found")

        with patch("PIL.ImageFont.truetype", side_effect=mock_truetype), \
             patch("PIL.ImageFont.load_default") as mock_default:
            font = cog._load_font(15)
            self.assertIsNotNone(font)
            self.assertIn("DejaVuSans.ttf", recorded_names)
            self.assertIn("LiberationSans-Regular.ttf", recorded_names)
            mock_default.assert_not_called()

        # Case 2: all fail, falls back to load_default
        with patch("PIL.ImageFont.truetype", side_effect=OSError), \
             patch("PIL.ImageFont.load_default", return_value="sentinel") as mock_default:
            font = cog._load_font(15, bold=True)
            self.assertEqual(font, "sentinel")
            mock_default.assert_called_once()

    def test_load_default_size_typeerror_fallback(self):
        cog = FamilyCommands(MagicMock())
        sentinel = MagicMock()
        with patch("PIL.ImageFont.truetype", side_effect=OSError), \
             patch("PIL.ImageFont.load_default", side_effect=[TypeError, sentinel]) as mock_default:
            font = cog._load_font(15)
            self.assertEqual(font, sentinel)
            self.assertEqual(mock_default.call_count, 2)

    async def test_handler_happy_path(self):
        cog = FamilyCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        guild = MagicMock()
        member1 = MagicMock()
        member1.id = 1
        member1.display_name = "UserOne"
        guild.members = [member1]
        interaction.guild = guild
        interaction.user = member1

        cog._fetch_relationship_rows = AsyncMock(return_value=([(1, 2)], []))

        await cog.family_tree.callback(cog, interaction, member1)

        interaction.response.defer.assert_awaited_once_with(thinking=True)
        interaction.followup.send.assert_awaited_once()
        args, kwargs = interaction.followup.send.call_args
        self.assertIn("file", kwargs)
        self.assertIn("allowed_mentions", kwargs)
        am = kwargs["allowed_mentions"]
        self.assertFalse(am.users)
        self.assertFalse(am.roles)
        self.assertFalse(am.everyone)
        self.assertIn("UserOne", args[0])

    async def test_handler_fetch_error(self):
        cog = FamilyCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        guild = MagicMock()
        member1 = MagicMock()
        member1.id = 1
        member1.display_name = "UserOne"
        guild.members = [member1]
        interaction.guild = guild
        interaction.user = member1

        cog._fetch_relationship_rows = AsyncMock(side_effect=RuntimeError("db error"))

        await cog.family_tree.callback(cog, interaction, member1)
        interaction.followup.send.assert_awaited_once_with("Couldn't render the family tree.")

    async def test_handler_render_error(self):
        cog = FamilyCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        guild = MagicMock()
        member1 = MagicMock()
        member1.id = 1
        member1.display_name = "UserOne"
        guild.members = [member1]
        interaction.guild = guild
        interaction.user = member1

        cog._fetch_relationship_rows = AsyncMock(return_value=([], []))
        with patch("asyncio.to_thread", side_effect=Exception("render error")):
            await cog.family_tree.callback(cog, interaction, member1)
            interaction.followup.send.assert_awaited_once_with("Couldn't render the family tree.")

    async def test_handler_truncated(self):
        cog = FamilyCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        guild = MagicMock()
        member1 = MagicMock()
        member1.id = 1
        member1.display_name = "UserOne"
        guild.members = [member1]
        interaction.guild = guild
        interaction.user = member1

        cog._fetch_relationship_rows = AsyncMock(return_value=([], []))
        with patch("cogs.family_commands.FamilyCommands._build_family_component", return_value=({1}, [], [], True)):
            await cog.family_tree.callback(cog, interaction, member1)
            interaction.followup.send.assert_awaited_once()
            args, _ = interaction.followup.send.call_args
            self.assertIn("closest relatives", args[0])

    async def test_handler_uses_to_thread_twice(self):
        cog = FamilyCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        guild = MagicMock()
        member1 = MagicMock()
        member1.id = 1
        member1.display_name = "UserOne"
        guild.members = [member1]
        interaction.guild = guild
        interaction.user = member1

        cog._fetch_relationship_rows = AsyncMock(return_value=([], []))
        with patch("asyncio.to_thread", new=AsyncMock(side_effect=[({1}, [], [], False), io.BytesIO(b"png")])) as mock_to_thread:
            await cog.family_tree.callback(cog, interaction, member1)
            self.assertEqual(mock_to_thread.await_count, 2)

    async def test_names_resolved_before_thread(self):
        cog = FamilyCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.followup.send = AsyncMock()
        guild = MagicMock()
        member1 = MagicMock()
        member1.id = 1
        member1.display_name = "UserOne"
        guild.members = [member1]
        interaction.guild = guild
        interaction.user = member1

        call_sequence = []
        original_names_for = cog._names_for

        def wrapped_names_for(g, ids):
            call_sequence.append("names")
            return original_names_for(g, ids)

        cog._names_for = wrapped_names_for
        cog._fetch_relationship_rows = AsyncMock(return_value=([], []))

        async def mock_to_thread(func, *args, **kwargs):
            call_sequence.append("thread")
            if "build" in func.__name__:
                return {1}, [], [], False
            return io.BytesIO(b"png")

        with patch("asyncio.to_thread", new=mock_to_thread):
            await cog.family_tree.callback(cog, interaction, member1)

        self.assertIn("names", call_sequence)
        self.assertIn("thread", call_sequence)
        self.assertEqual(call_sequence[0], "names")

if __name__ == "__main__":
    unittest.main()
