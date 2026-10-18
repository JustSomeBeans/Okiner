import sqlite3
import unittest
from database import INTEGRITY_TRIGGERS_SQL

class TestDBInvariants(unittest.TestCase):
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
        # Verify valid insert works
        try:
            conn_a.execute("INSERT INTO marriages (spouse1_id, spouse2_id, marriage_date) VALUES (10, 20, '1000')")
            conn_a.commit()
            print("Drop-before-rename (a): Rebuild succeeded and valid insert committed successfully.")
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

        # Attempt insert and observe behavior
        try:
            conn_b.execute("INSERT INTO marriages (spouse1_id, spouse2_id, marriage_date) VALUES (15, 25, '1000')")
            conn_b.commit()
            print("Drop-before-rename (b): Insert succeeded (trigger references legacy table).")
        except sqlite3.Error as e:
            print(f"Drop-before-rename (b): Insert failed with error: {e}")
        conn_b.close()

if __name__ == "__main__":
    unittest.main()
