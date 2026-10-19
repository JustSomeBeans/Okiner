import asyncio
import tempfile
import pathlib
import os
import sqlite3
import unittest
import asqlite
from database import create_rp_type_with_entries, set_bot

class StubBot:
    def __init__(self, db_pool):
        self.db_pool = db_pool

class TestRPCreate(unittest.IsolatedAsyncioTestCase):
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
            await conn.commit()

    async def asyncTearDown(self):
        await self.pool.close()
        pathlib.Path(self.db_path).unlink(missing_ok=True)

    async def test_success_rp_create(self):
        guild_id = 100
        user_id = 200
        rp_type = "hug"
        entries = [
            {"case_type": "standard", "url": "https://i.imgur.com/a.png", "text": None, "action_text": None},
            {"case_type": "standard", "url": None, "text": "hugs you", "action_text": None},
            {"case_type": "standard", "url": None, "text": None, "action_text": "{user} hugs {target}"},
        ]
        await create_rp_type_with_entries(guild_id, user_id, rp_type, entries)

        async with self.pool.acquire() as conn:
            # Check type row exists
            cursor = await conn.execute("SELECT 1 FROM rp_types WHERE guild_id = ? AND type = ?", (guild_id, rp_type))
            self.assertIsNotNone(await cursor.fetchone())

            # Check entries with ORDER BY rowid
            cursor = await conn.execute("SELECT case_type, url, texts, action_texts FROM roleplay_entries WHERE guild_id = ? AND type = ? ORDER BY rowid", (guild_id, rp_type))
            rows = await cursor.fetchall()
            self.assertEqual(len(rows), 3)
            self.assertEqual(tuple(rows[0]), ("standard", "https://i.imgur.com/a.png", None, None))
            self.assertEqual(tuple(rows[1]), ("standard", None, "hugs you", None))
            self.assertEqual(tuple(rows[2]), ("standard", None, None, "{user} hugs {target}"))

    async def test_payload_deduplication(self):
        guild_id = 100
        user_id = 200
        rp_type = "poke"
        entries = [
            {"case_type": "standard", "url": None, "text": "pokes you", "action_text": None},
            {"case_type": "standard", "url": None, "text": "pokes you", "action_text": None}, # Duplicate
        ]
        await create_rp_type_with_entries(guild_id, user_id, rp_type, entries)

        async with self.pool.acquire() as conn:
            cursor = await conn.execute("SELECT COUNT(*) FROM roleplay_entries WHERE guild_id = ? AND type = ?", (guild_id, rp_type))
            count = (await cursor.fetchone())[0]
            self.assertEqual(count, 1)

    async def test_existing_type_raises_integrity_error(self):
        guild_id = 100
        user_id = 200
        rp_type = "wave"
        entries = [{"case_type": "standard", "url": None, "text": "waves", "action_text": None}]
        await create_rp_type_with_entries(guild_id, user_id, rp_type, entries)

        with self.assertRaises(sqlite3.IntegrityError):
            await create_rp_type_with_entries(guild_id, user_id, rp_type, [{"case_type": "standard", "url": None, "text": "waves again", "action_text": None}])

        async with self.pool.acquire() as conn:
            cursor = await conn.execute("SELECT COUNT(*) FROM roleplay_entries WHERE guild_id = ? AND type = ?", (guild_id, rp_type))
            count = (await cursor.fetchone())[0]
            self.assertEqual(count, 1) # Only first payload entries exist

    async def test_mid_payload_failure_rolls_back_everything(self):
        guild_id = 100
        user_id = 200
        rp_type = "slap"
        # First entry valid, second entry has case_type=None (violating NOT NULL)
        entries = [
            {"case_type": "standard", "url": None, "text": "slaps", "action_text": None},
            {"case_type": None, "url": None, "text": "bad", "action_text": None},
        ]
        with self.assertRaises(sqlite3.IntegrityError):
            await create_rp_type_with_entries(guild_id, user_id, rp_type, entries)

        async with self.pool.acquire() as conn:
            cursor = await conn.execute("SELECT 1 FROM rp_types WHERE guild_id = ? AND type = ?", (guild_id, rp_type))
            self.assertIsNone(await cursor.fetchone())

            cursor = await conn.execute("SELECT COUNT(*) FROM roleplay_entries WHERE guild_id = ? AND type = ?", (guild_id, rp_type))
            count = (await cursor.fetchone())[0]
            self.assertEqual(count, 0)

    async def test_asyncio_gather_race(self):
        guild_id = 100
        user_id = 200
        rp_type = "smile"
        payload_a = [
            {"case_type": "standard", "url": None, "text": "smiles A1", "action_text": None},
            {"case_type": "standard", "url": None, "text": "smiles A2", "action_text": None},
        ]
        payload_b = [
            {"case_type": "standard", "url": None, "text": "smiles B1", "action_text": None},
            {"case_type": "standard", "url": None, "text": "smiles B2", "action_text": None},
            {"case_type": "standard", "url": None, "text": "smiles B3", "action_text": None},
        ]
        results = await asyncio.gather(
            create_rp_type_with_entries(guild_id, user_id, rp_type, payload_a),
            create_rp_type_with_entries(guild_id, user_id, rp_type, payload_b),
            return_exceptions=True
        )
        successes = [r for r in results if r is None]
        errors = [r for r in results if isinstance(r, sqlite3.IntegrityError)]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)

        async with self.pool.acquire() as conn:
            cursor = await conn.execute("SELECT texts FROM roleplay_entries WHERE guild_id = ? AND type = ? ORDER BY rowid", (guild_id, rp_type))
            rows = await cursor.fetchall()
            texts = [r[0] for r in rows]
            # Must be exactly all of A or exactly all of B, never a mix, and loser left nothing behind
            if texts[0].startswith("smiles A"):
                self.assertEqual(texts, ["smiles A1", "smiles A2"])
            else:
                self.assertEqual(texts, ["smiles B1", "smiles B2", "smiles B3"])

    async def test_no_leaked_transaction_after_failure(self):
        guild_id = 100
        user_id = 200
        rp_type = "wink"
        with self.assertRaises(sqlite3.IntegrityError):
            await create_rp_type_with_entries(guild_id, user_id, rp_type, [{"case_type": None, "url": None, "text": "bad", "action_text": None}])

        # Subsequent valid create must succeed
        await create_rp_type_with_entries(guild_id, user_id, rp_type, [{"case_type": "standard", "url": None, "text": "winks", "action_text": None}])

    async def test_guild_isolation(self):
        user_id = 200
        rp_type = "hug"
        await create_rp_type_with_entries(101, user_id, rp_type, [{"case_type": "standard", "url": None, "text": "hug A", "action_text": None}])
        await create_rp_type_with_entries(102, user_id, rp_type, [{"case_type": "standard", "url": None, "text": "hug B", "action_text": None}])

        async with self.pool.acquire() as conn:
            cursor = await conn.execute("SELECT texts FROM roleplay_entries WHERE guild_id = 101 AND type = ?", (rp_type,))
            self.assertEqual((await cursor.fetchone())[0], "hug A")
            cursor = await conn.execute("SELECT texts FROM roleplay_entries WHERE guild_id = 102 AND type = ?", (rp_type,))
            self.assertEqual((await cursor.fetchone())[0], "hug B")

if __name__ == "__main__":
    unittest.main()
