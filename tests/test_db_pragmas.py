import tempfile
import pathlib
import os
import sqlite3
import unittest
import inspect
import asqlite
from database import init_connection, assert_connection_pragmas, add_rp_entry, set_bot
from bot import OkinerBot

class StubBot:
    def __init__(self, db_pool):
        self.db_pool = db_pool

class TestDBPragmas(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.db_fd)

    async def asyncTearDown(self):
        pathlib.Path(self.db_path).unlink(missing_ok=True)
        pathlib.Path(self.db_path + "-wal").unlink(missing_ok=True)
        pathlib.Path(self.db_path + "-shm").unlink(missing_ok=True)

    # 1. Pool created with init=database.init_connection: size 3 connections all have correct pragmas
    async def test_pool_init_connection_pragmas(self):
        pool = await asqlite.create_pool(self.db_path, size=3, init=init_connection)
        try:
            async with pool.acquire() as c1, pool.acquire() as c2, pool.acquire() as c3:
                for conn in [c1, c2, c3]:
                    cur = await conn.execute("PRAGMA foreign_keys")
                    fk = (await cur.fetchone())[0]
                    self.assertEqual(fk, 1)

                    cur = await conn.execute("PRAGMA busy_timeout")
                    bt = (await cur.fetchone())[0]
                    self.assertEqual(bt, 5000)

                    cur = await conn.execute("PRAGMA journal_mode")
                    jm = (await cur.fetchone())[0]
                    self.assertEqual(jm.lower(), "wal")

                    cur = await conn.execute("PRAGMA synchronous")
                    sync = (await cur.fetchone())[0]
                    self.assertEqual(sync, 1)
        finally:
            await pool.close()

    # 2. Positive control: pool created without init reports synchronous == 2 (default) on a held connection (proves the test can fail)
    async def test_pool_without_init_synchronous_two(self):
        pool = await asqlite.create_pool(self.db_path, size=1)
        try:
            async with pool.acquire() as conn:
                cur = await conn.execute("PRAGMA synchronous")
                sync = (await cur.fetchone())[0]
                self.assertEqual(sync, 2)
        finally:
            await pool.close()

    # 3. FK enforcement via helper path with init pool and schema loaded
    async def test_fk_enforcement_helper_path(self):
        pool = await asqlite.create_pool(self.db_path, size=1, init=init_connection)
        stub_bot = StubBot(pool)
        set_bot(stub_bot)
        try:
            async with pool.acquire() as conn:
                schema_path = pathlib.Path(__file__).resolve().parent.parent / "rp_schema.sql"
                await conn.executescript(schema_path.read_text(encoding="utf-8"))
                await conn.commit()

            with self.assertRaises(sqlite3.IntegrityError):
                await add_rp_entry(1, 111, "nope", text="x")
        finally:
            await pool.close()

    # 4. assert_connection_pragmas passes with init pool and raises RuntimeError with non-init pool
    async def test_assert_connection_pragmas(self):
        init_pool = await asqlite.create_pool(self.db_path, size=1, init=init_connection)
        set_bot(StubBot(init_pool))
        try:
            await assert_connection_pragmas()
        finally:
            await init_pool.close()

        no_init_pool = await asqlite.create_pool(self.db_path, size=1)
        set_bot(StubBot(no_init_pool))
        try:
            with self.assertRaises(RuntimeError):
                await assert_connection_pragmas()
        finally:
            await no_init_pool.close()

    # 5. Direct test of init_connection function on raw sqlite3 connection (catches m1, m2, m3)
    def test_init_connection_direct(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            raw_conn = sqlite3.connect(path)
            raw_conn.execute("PRAGMA foreign_keys = OFF")
            raw_conn.execute("PRAGMA busy_timeout = 0")
            raw_conn.execute("PRAGMA journal_mode = DELETE")
            raw_conn.execute("PRAGMA synchronous = FULL")

            init_connection(raw_conn)

            fk = raw_conn.execute("PRAGMA foreign_keys").fetchone()[0]
            bt = raw_conn.execute("PRAGMA busy_timeout").fetchone()[0]
            jm = raw_conn.execute("PRAGMA journal_mode").fetchone()[0]
            sync = raw_conn.execute("PRAGMA synchronous").fetchone()[0]

            self.assertEqual(fk, 1)
            self.assertEqual(bt, 5000)
            self.assertEqual(jm.lower(), "wal")
            self.assertEqual(sync, 1)
            raw_conn.close()
        finally:
            pathlib.Path(path).unlink(missing_ok=True)
            pathlib.Path(path + "-wal").unlink(missing_ok=True)
            pathlib.Path(path + "-shm").unlink(missing_ok=True)

    # 6. Source inspection test for setup_hook passing init (catches m4)
    def test_setup_hook_passes_init_hook(self):
        source = inspect.getsource(OkinerBot.setup_hook)
        self.assertIn("init=database.init_connection", source)

if __name__ == "__main__":
    unittest.main()
