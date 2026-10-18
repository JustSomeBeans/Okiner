import asyncio
import tempfile
import pathlib
import os
import sqlite3
import unittest
import asqlite
from database import INTEGRITY_TRIGGERS_SQL, add_marriage, add_child, find_multi_marriage_users, set_bot

class StubBot:
    def __init__(self, db_pool):
        self.db_pool = db_pool

class TestDBInvariants(unittest.IsolatedAsyncioTestCase):
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

    def test_migration_and_triggers(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys = ON")
        
        # 1. Setup old pre-unique layout for marriages and children
        conn.executescript("""
            CREATE TABLE marriages (
                marriage_id INTEGER PRIMARY KEY,
                spouse1_id INTEGER,
                spouse2_id INTEGER,
                marriage_date TEXT
            );
            CREATE TABLE children (
                offspring_id INTEGER PRIMARY KEY AUTOINCREMENT,
                child_id INTEGER,
                parent_id INTEGER,
                adoption_date TEXT
            );
            
            -- Insert legacy data (including pre-existing overlap/bigamy which must be preserved)
            INSERT INTO marriages (spouse1_id, spouse2_id, marriage_date) VALUES (1, 5, '1000');
            INSERT INTO marriages (spouse1_id, spouse2_id, marriage_date) VALUES (5, 9, '1000');
            INSERT INTO children (child_id, parent_id, adoption_date) VALUES (10, 1, '1000');
        """)
        
        # 2. Run migration path (simulating bot.py migrations)
        conn.executescript("""
            ALTER TABLE children RENAME TO children_legacy;
            CREATE TABLE children (
                offspring_id INTEGER PRIMARY KEY AUTOINCREMENT,
                child_id INTEGER UNIQUE NOT NULL,
                parent_id INTEGER NOT NULL,
                adoption_date TEXT
            );
            INSERT INTO children (offspring_id, child_id, parent_id, adoption_date)
            SELECT offspring_id, child_id, parent_id, adoption_date FROM children_legacy;
            DROP TABLE children_legacy;
        """)
        
        conn.executescript("""
            ALTER TABLE marriages RENAME TO marriages_legacy;
            CREATE TABLE marriages (
                marriage_id INTEGER PRIMARY KEY,
                spouse1_id INTEGER UNIQUE NOT NULL,
                spouse2_id INTEGER UNIQUE NOT NULL,
                marriage_date TEXT,
                UNIQUE (spouse1_id, spouse2_id)
            );
            INSERT INTO marriages (marriage_id, spouse1_id, spouse2_id, marriage_date)
            SELECT marriage_id, spouse1_id, spouse2_id, marriage_date FROM marriages_legacy;
            DROP TABLE marriages_legacy;
        """)
        
        # 3. Apply INTEGRITY_TRIGGERS_SQL from database.py
        conn.executescript(INTEGRITY_TRIGGERS_SQL)
        conn.commit()
        
        # 4. Assert legacy rows are still present in marriages (count == 2)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM marriages")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 2, "Legacy marriage rows must be preserved exactly as-is after migration.")
        print(f"Legacy rows check passed: found {count} marriage rows.")

        # 5. Positive controls: valid marriage and valid adoption must succeed
        try:
            conn.execute("INSERT INTO marriages (spouse1_id, spouse2_id, marriage_date) VALUES (2, 3, '1000')")
            conn.commit()
        except sqlite3.Error as e:
            self.fail(f"Positive control marriage (2, 3) failed unexpectedly: {e}")

        try:
            conn.execute("INSERT INTO children (child_id, parent_id, adoption_date) VALUES (30, 2, '1000')")
            conn.commit()
        except sqlite3.Error as e:
            self.fail(f"Positive control adoption (child 30, parent 2) failed unexpectedly: {e}")

        print("Positive controls passed successfully.")

        # 6. Negative controls (trigger constraints)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO marriages (spouse1_id, spouse2_id, marriage_date) VALUES (4, 4, '1000')")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO marriages (spouse1_id, spouse2_id, marriage_date) VALUES (6, 4, '1000')")
            
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO marriages (spouse1_id, spouse2_id, marriage_date) VALUES (1, 8, '1000')")
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO marriages (spouse1_id, spouse2_id, marriage_date) VALUES (2, 5, '1000')")
            
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO marriages (spouse1_id, spouse2_id, marriage_date) VALUES (1, 10, '1000')")

        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO children (child_id, parent_id, adoption_date) VALUES (20, 20, '1000')")

        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO children (child_id, parent_id, adoption_date) VALUES (1, 10, '1000')")

        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO children (child_id, parent_id, adoption_date) VALUES (1, 5, '1000')")

        print("Negative controls (trigger constraints) passed successfully.")
        conn.close()

    def test_drop_before_rename_ordering(self):
        # (a) WITH DROP TRIGGER statements executed first
        conn_a = sqlite3.connect(":memory:")
        conn_a.execute("PRAGMA foreign_keys = ON")
        conn_a.executescript("""
            CREATE TABLE marriages (
                marriage_id INTEGER PRIMARY KEY,
                spouse1_id INTEGER UNIQUE NOT NULL,
                spouse2_id INTEGER UNIQUE NOT NULL,
                marriage_date TEXT,
                UNIQUE (spouse1_id, spouse2_id)
            );
            CREATE TABLE children (
                offspring_id INTEGER PRIMARY KEY AUTOINCREMENT,
                child_id INTEGER UNIQUE NOT NULL,
                parent_id INTEGER NOT NULL,
                adoption_date TEXT
            );
        """)
        conn_a.executescript(INTEGRITY_TRIGGERS_SQL)
        
        # Rebuild with drops first
        conn_a.executescript("""
            DROP TRIGGER IF EXISTS trg_marriages_ordering;
            DROP TRIGGER IF EXISTS trg_marriages_bigamy;
            DROP TRIGGER IF EXISTS trg_marriages_parent_child;
            DROP TRIGGER IF EXISTS trg_children_self;
            DROP TRIGGER IF EXISTS trg_children_reverse;
            DROP TRIGGER IF EXISTS trg_children_spouse;

            ALTER TABLE marriages RENAME TO marriages_legacy;
            CREATE TABLE marriages (
                marriage_id INTEGER PRIMARY KEY,
                spouse1_id INTEGER UNIQUE NOT NULL,
                spouse2_id INTEGER UNIQUE NOT NULL,
                marriage_date TEXT,
                UNIQUE (spouse1_id, spouse2_id)
            );
            INSERT INTO marriages SELECT * FROM marriages_legacy;
            DROP TABLE marriages_legacy;
        """)
        conn_a.executescript(INTEGRITY_TRIGGERS_SQL)
        # Verify valid insert works for both marriages and children (disjoint IDs to avoid spouse adoption rule)
        try:
            conn_a.execute("INSERT INTO marriages (spouse1_id, spouse2_id, marriage_date) VALUES (10, 20, '1000')")
            conn_a.execute("INSERT INTO children (child_id, parent_id, adoption_date) VALUES (15, 25, '1000')")
            conn_a.commit()
            print("Drop-before-rename (a): Rebuild succeeded and valid inserts into marriages and children committed successfully.")
        except sqlite3.Error as e:
            self.fail(f"(a) Failed: {e}")
        conn_a.close()

        # (b) WITHOUT DROP TRIGGER before rename
        conn_b = sqlite3.connect(":memory:")
        conn_b.execute("PRAGMA foreign_keys = ON")
        conn_b.executescript("""
            CREATE TABLE marriages (
                marriage_id INTEGER PRIMARY KEY,
                spouse1_id INTEGER UNIQUE NOT NULL,
                spouse2_id INTEGER UNIQUE NOT NULL,
                marriage_date TEXT,
                UNIQUE (spouse1_id, spouse2_id)
            );
            CREATE TABLE children (
                offspring_id INTEGER PRIMARY KEY AUTOINCREMENT,
                child_id INTEGER UNIQUE NOT NULL,
                parent_id INTEGER NOT NULL,
                adoption_date TEXT
            );
        """)
        conn_b.executescript(INTEGRITY_TRIGGERS_SQL)
        
        # Rebuild WITHOUT dropping triggers first
        conn_b.executescript("""
            ALTER TABLE marriages RENAME TO marriages_legacy;
            CREATE TABLE marriages (
                marriage_id INTEGER PRIMARY KEY,
                spouse1_id INTEGER UNIQUE NOT NULL,
                spouse2_id INTEGER UNIQUE NOT NULL,
                marriage_date TEXT,
                UNIQUE (spouse1_id, spouse2_id)
            );
            INSERT INTO marriages SELECT * FROM marriages_legacy;
            DROP TABLE marriages_legacy;
        """)
        
        # Inspect trigger sql in sqlite_master
        cursor = conn_b.cursor()
        cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='trigger'")
        triggers_sql = cursor.fetchall()
        print("Observation without DROP TRIGGER before rename:")
        for trig_name, trig_sql in triggers_sql:
            print(f"  Trigger {trig_name}: {trig_sql}")
            if "marriages_legacy" in (trig_sql or ""):
                print("    -> Observed: SQLite automatically rewrote trigger body referencing renamed table 'marriages' to 'marriages_legacy'!")

        # Attempt insert into children (which references marriages_legacy) and print resulting error
        try:
            conn_b.execute("INSERT INTO children (child_id, parent_id, adoption_date) VALUES (15, 25, '1000')")
            conn_b.commit()
            print("Drop-before-rename (b): Insert into children succeeded.")
        except sqlite3.Error as e:
            print(f"Drop-before-rename (b): Insert into children failed with expected error: {e}")
        conn_b.close()

    async def test_add_marriage_and_child_helpers(self):
        # 1. Valid marriage and valid adoption succeed
        await add_marriage(10, 20, 1760000000)
        await add_child(100, 10, 1760000001)

        # 2. Unsorted input (5, 1) is stored sorted as (1, 5)
        await add_marriage(5, 1, 1760000002)
        async with self.pool.acquire() as conn:
            cursor = await conn.execute("SELECT spouse1_id, spouse2_id FROM marriages WHERE spouse1_id = 1 OR spouse2_id = 1")
            row = await cursor.fetchone()
            self.assertEqual((row[0], row[1]), (1, 5))

        # 3. Bigamy via the real function raises IntegrityError
        with self.assertRaises(sqlite3.IntegrityError):
            await add_marriage(1, 99, 1760000003)

        # 4. 3-cycle A->B->C->A is rejected on the third add_child
        await add_child(201, 200, 1760000004)
        await add_child(202, 201, 1760000005)
        with self.assertRaises(sqlite3.IntegrityError):
            await add_child(200, 202, 1760000006)

        # 5. asyncio.gather of add_marriage(300, 301) and add_marriage(301, 302) yields exactly one success and one IntegrityError
        results = await asyncio.gather(
            add_marriage(300, 301, 1760000007),
            add_marriage(301, 302, 1760000008),
            return_exceptions=True
        )
        successes = [r for r in results if r is None]
        errors = [r for r in results if isinstance(r, sqlite3.IntegrityError)]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)

        # 6. After a rejected insert, a following valid insert on the same pool still works (proves no leaked open transaction)
        with self.assertRaises(sqlite3.IntegrityError):
            await add_marriage(10, 20, 1760000009) # duplicate/bigamy conflict

        await add_marriage(400, 401, 1760000010) # Should succeed

    async def test_text_affinity(self):
        ts_m = 1760000000
        ts_c = 1760000001
        await add_marriage(1, 2, ts_m)
        await add_child(10, 1, ts_c)

        async with self.pool.acquire() as conn:
            cursor = await conn.execute("SELECT marriage_date FROM marriages WHERE spouse1_id = 1 AND spouse2_id = 2")
            m_row = await cursor.fetchone()
            self.assertEqual(m_row[0], str(ts_m))
            self.assertIsInstance(m_row[0], str)

            cursor = await conn.execute("SELECT adoption_date FROM children WHERE child_id = 10 AND parent_id = 1")
            c_row = await cursor.fetchone()
            self.assertEqual(c_row[0], str(ts_c))
            self.assertIsInstance(c_row[0], str)

    async def test_find_multi_marriage_users(self):
        # (a) A DB containing legacy rows (1, 5) and (5, 9) returns [5]
        async with self.pool.acquire() as conn:
            await conn.executescript("""
                DROP TRIGGER IF EXISTS trg_marriages_ordering;
                DROP TRIGGER IF EXISTS trg_marriages_bigamy;
                DROP TRIGGER IF EXISTS trg_marriages_parent_child;
                DELETE FROM marriages;
                INSERT INTO marriages (spouse1_id, spouse2_id, marriage_date) VALUES (1, 5, '1000');
                INSERT INTO marriages (spouse1_id, spouse2_id, marriage_date) VALUES (5, 9, '1000');
            """)
            await conn.executescript(INTEGRITY_TRIGGERS_SQL)
            await conn.commit()

        multi = await find_multi_marriage_users()
        self.assertEqual(multi, [5])

        # (b) A clean DB returns []
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM marriages")
            await conn.commit()

        multi_clean = await find_multi_marriage_users()
        self.assertEqual(multi_clean, [])

        # (c) The function does not change the marriages row count
        async with self.pool.acquire() as conn:
            await conn.executescript("""
                DROP TRIGGER IF EXISTS trg_marriages_ordering;
                DROP TRIGGER IF EXISTS trg_marriages_bigamy;
                DROP TRIGGER IF EXISTS trg_marriages_parent_child;
                DELETE FROM marriages;
                INSERT INTO marriages (spouse1_id, spouse2_id, marriage_date) VALUES (1, 2, '1000');
                INSERT INTO marriages (spouse1_id, spouse2_id, marriage_date) VALUES (3, 4, '1000');
            """)
            await conn.executescript(INTEGRITY_TRIGGERS_SQL)
            await conn.commit()
            
            cursor = await conn.execute("SELECT COUNT(*) FROM marriages")
            count_before = (await cursor.fetchone())[0]

        _ = await find_multi_marriage_users()

        async with self.pool.acquire() as conn:
            cursor = await conn.execute("SELECT COUNT(*) FROM marriages")
            count_after = (await cursor.fetchone())[0]

        self.assertEqual(count_before, count_after)

if __name__ == "__main__":
    unittest.main()
