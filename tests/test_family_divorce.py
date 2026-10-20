import tempfile
import pathlib
import os
import sqlite3
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import asqlite
import discord
from database import INTEGRITY_TRIGGERS_SQL, execute_write, set_bot
from cogs.family_commands import FamilyCommands

class StubBot:
    def __init__(self, db_pool):
        self.db_pool = db_pool

class TestFamilyDivorceDisown(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)
        self.pool = await asqlite.create_pool(self.db_path)
        self.stub_bot = StubBot(self.pool)
        set_bot(self.stub_bot)

        async with self.pool.acquire() as conn:
            await conn.execute("PRAGMA foreign_keys = ON")
            schema_path = pathlib.Path(__file__).resolve().parent.parent / "rp_schema.sql"
            await conn.executescript(schema_path.read_text(encoding="utf-8"))
            await conn.executescript(INTEGRITY_TRIGGERS_SQL)
            await conn.commit()

    async def asyncTearDown(self):
        await self.pool.close()
        pathlib.Path(self.db_path).unlink(missing_ok=True)

    # 1. Success order: divorce
    async def test_divorce_success_order(self):
        cog = FamilyCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user.id = 10
        user = MagicMock(spec=discord.User)
        user.id = 20
        user.display_name = "User20"
        user.mention = "<@20>"

        call_order = []

        async def mock_fetch_one(*args, **kwargs):
            return (1,)

        async def mock_execute_write(query, params):
            call_order.append(("execute_write", query, params))
            return 1

        async def mock_send_message(*args, **kwargs):
            call_order.append(("send_message", args, kwargs))

        interaction.response.send_message = mock_send_message

        with patch("cogs.family_commands.fetch_one", new=mock_fetch_one), \
             patch("cogs.family_commands.execute_write", new=mock_execute_write):

            await cog.divorce.callback(cog, interaction, user)

        self.assertEqual(len(call_order), 2)
        self.assertEqual(call_order[0][0], "execute_write")
        self.assertEqual(call_order[1][0], "send_message")
        self.assertEqual(call_order[0][1], "DELETE FROM marriages WHERE spouse1_id = ? AND spouse2_id = ?")
        self.assertEqual(call_order[0][2], (10, 20))
        msg_content = call_order[1][1][0]
        self.assertIn("decided to divorce you", msg_content)
        self.assertIn(user.mention, msg_content)

    # 1. Success order: disown
    async def test_disown_success_order(self):
        cog = FamilyCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user.id = 10
        user = MagicMock(spec=discord.User)
        user.id = 30
        user.bot = False
        user.display_name = "Child30"
        user.mention = "<@30>"

        call_order = []

        async def mock_fetch_one(*args, **kwargs):
            return (1,)

        async def mock_execute_write(query, params):
            call_order.append(("execute_write", query, params))
            return 1

        async def mock_send_message(*args, **kwargs):
            call_order.append(("send_message", args, kwargs))

        interaction.response.send_message = mock_send_message

        with patch("cogs.family_commands.fetch_one", new=mock_fetch_one), \
             patch("cogs.family_commands.execute_write", new=mock_execute_write):

            await cog.disown.callback(cog, interaction, user)

        self.assertEqual(len(call_order), 2)
        self.assertEqual(call_order[0][0], "execute_write")
        self.assertEqual(call_order[1][0], "send_message")
        self.assertEqual(call_order[0][1], "DELETE FROM children WHERE child_id = ? AND parent_id = ?")
        self.assertEqual(call_order[0][2], (30, 10))
        msg_content = call_order[1][1][0]
        self.assertIn("decided to disown you", msg_content)
        self.assertIn(user.mention, msg_content)

    # 2. Rowcount 0: divorce
    async def test_divorce_rowcount_zero(self):
        cog = FamilyCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user.id = 10
        user = MagicMock(spec=discord.User)
        user.id = 20
        user.display_name = "User20"
        interaction.response.send_message = AsyncMock()

        with patch("cogs.family_commands.fetch_one", new=AsyncMock(return_value=(1,))), \
             patch("cogs.family_commands.execute_write", new=AsyncMock(return_value=0)) as mock_write:

            await cog.divorce.callback(cog, interaction, user)

            mock_write.assert_awaited_once()
            interaction.response.send_message.assert_awaited_once()
            args, _ = interaction.response.send_message.call_args
            self.assertIn("You're no longer married to", args[0])
            self.assertNotIn("decided to divorce you", args[0])

    # 2. Rowcount 0: disown
    async def test_disown_rowcount_zero(self):
        cog = FamilyCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user.id = 10
        user = MagicMock(spec=discord.User)
        user.id = 30
        user.bot = False
        user.display_name = "Child30"
        interaction.response.send_message = AsyncMock()

        with patch("cogs.family_commands.fetch_one", new=AsyncMock(return_value=(1,))), \
             patch("cogs.family_commands.execute_write", new=AsyncMock(return_value=0)) as mock_write:

            await cog.disown.callback(cog, interaction, user)

            mock_write.assert_awaited_once()
            interaction.response.send_message.assert_awaited_once()
            args, _ = interaction.response.send_message.call_args
            self.assertIn("is no longer your child", args[0])
            self.assertNotIn("decided to disown you", args[0])

    # 3. execute_write raises OperationalError: divorce and disown
    async def test_divorce_disown_raises_db_error(self):
        cog = FamilyCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user.id = 10
        user = MagicMock(spec=discord.User)
        user.id = 20
        user.bot = False
        user.display_name = "User20"
        interaction.response.send_message = AsyncMock()

        with patch("cogs.family_commands.fetch_one", new=AsyncMock(return_value=(1,))), \
             patch("cogs.family_commands.execute_write", new=AsyncMock(side_effect=sqlite3.OperationalError)):

            with self.assertRaises(sqlite3.OperationalError):
                await cog.divorce.callback(cog, interaction, user)
            interaction.response.send_message.assert_not_awaited()

            with self.assertRaises(sqlite3.OperationalError):
                await cog.disown.callback(cog, interaction, user)
            interaction.response.send_message.assert_not_awaited()

    # 4. Pre-check miss: divorce and disown
    async def test_divorce_disown_precheck_miss(self):
        cog = FamilyCommands(MagicMock())
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user.id = 10
        user = MagicMock(spec=discord.User)
        user.id = 20
        user.bot = False
        user.display_name = "User20"
        interaction.response.send_message = AsyncMock()

        with patch("cogs.family_commands.fetch_one", new=AsyncMock(return_value=None)), \
             patch("cogs.family_commands.execute_write", new=AsyncMock()) as mock_write:

            await cog.divorce.callback(cog, interaction, user)
            mock_write.assert_not_awaited()
            interaction.response.send_message.assert_awaited_once()

            interaction.response.send_message.reset_mock()
            await cog.disown.callback(cog, interaction, user)
            mock_write.assert_not_awaited()
            interaction.response.send_message.assert_awaited_once()

    # 5. Real-DB execute_write: delete existing row returns 1 and row is gone
    async def test_execute_write_delete_existing(self):
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO marriages (spouse1_id, spouse2_id) VALUES (1, 2)")
            await conn.commit()

        rowcount = await execute_write("DELETE FROM marriages WHERE spouse1_id = ? AND spouse2_id = ?", (1, 2))
        self.assertEqual(rowcount, 1)

        async with self.pool.acquire() as conn:
            cursor = await conn.execute("SELECT 1 FROM marriages WHERE spouse1_id = 1 AND spouse2_id = 2")
            self.assertIsNone(await cursor.fetchone())

    # 6. Real-DB execute_write: delete non-existent row returns 0
    async def test_execute_write_delete_nonexistent(self):
        rowcount = await execute_write("DELETE FROM marriages WHERE spouse1_id = ? AND spouse2_id = ?", (99, 100))
        self.assertEqual(rowcount, 0)

    # 7. Real-DB execute_write: statement that raises re-raises AND subsequent write works
    async def test_execute_write_rollback_and_subsequent_success(self):
        with self.assertRaises(sqlite3.OperationalError):
            await execute_write("DELETE FROM non_existent_table")

        # Subsequent write works
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO marriages (spouse1_id, spouse2_id) VALUES (5, 6)")
            await conn.commit()

        rowcount = await execute_write("DELETE FROM marriages WHERE spouse1_id = ? AND spouse2_id = ?", (5, 6))
        self.assertEqual(rowcount, 1)

    # 8. Real-DB execute_write: commit is persisted verified via separate sqlite3.connect
    async def test_execute_write_persistence_separate_connection(self):
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO marriages (spouse1_id, spouse2_id) VALUES (3, 4)")
            await conn.commit()

        rowcount = await execute_write("DELETE FROM marriages WHERE spouse1_id = ? AND spouse2_id = ?", (3, 4))
        self.assertEqual(rowcount, 1)

        raw_conn = sqlite3.connect(self.db_path)
        try:
            cursor = raw_conn.execute("SELECT 1 FROM marriages WHERE spouse1_id = 3 AND spouse2_id = 4")
            self.assertIsNone(cursor.fetchone())
        finally:
            raw_conn.close()

    # 9. Real-DB execute_write: failure does not leak transaction (catches m6 missing rollback)
    async def test_execute_write_failure_does_not_leak_transaction(self):
        pool = await asqlite.create_pool(self.db_path, size=1)
        stub_bot = StubBot(pool)
        set_bot(stub_bot)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                await execute_write("INSERT INTO marriages (spouse1_id, spouse2_id) VALUES (?, ?)", (2, 2))

            async with pool.acquire() as conn:
                await conn.execute("INSERT INTO marriages (spouse1_id, spouse2_id) VALUES (9, 10)")
                await conn.commit()

            rowcount = await execute_write("DELETE FROM marriages WHERE spouse1_id = ? AND spouse2_id = ?", (9, 10))
            self.assertEqual(rowcount, 1)
        finally:
            await pool.close()
            set_bot(self.stub_bot)

if __name__ == "__main__":
    unittest.main()
