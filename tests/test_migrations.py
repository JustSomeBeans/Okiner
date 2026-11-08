import tempfile
import pathlib
import os
import sqlite3
import unittest
from unittest.mock import patch

from migrations import run_migrations, split_statements, MIGRATIONS
from database import INTEGRITY_TRIGGERS_SQL


def _next_version():
    return max(v for v, _ in MIGRATIONS) + 1


class TestMigrations(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "rp.db")
        schema_path = pathlib.Path(__file__).resolve().parent.parent / "rp_schema.sql"
        self.schema_sql = schema_path.read_text(encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _get_triggers(self, conn):
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        return [row[0] for row in cur.fetchall()]

    def _get_backups(self):
        return [f for f in os.listdir(self.temp_dir.name) if f.startswith("rp.db.bak-") and not f.endswith(("-wal", "-shm"))]

    def _has_single_column_unique_index(self, conn, table_name, column_name):
        index_list = conn.execute(f"PRAGMA index_list({table_name!r})").fetchall()
        for idx in index_list:
            if idx[2] == 1:
                idx_name = idx[1]
                cols = conn.execute(f"PRAGMA index_info({idx_name!r})").fetchall()
                indexed_cols = [c[2] for c in cols]
                if indexed_cols == [column_name]:
                    return True
        return False

    # 1. Fresh empty DB
    def test_fresh_empty_db(self):
        applied = run_migrations(self.db_path, self.schema_sql)
        self.assertEqual(applied, [1, 2])

        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute("PRAGMA user_version")
            self.assertEqual(cur.fetchone()[0], 2)

            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cur.fetchall()}
            self.assertIn("rp_types", tables)
            self.assertIn("roleplay_entries", tables)
            self.assertIn("marriages", tables)
            self.assertIn("children", tables)

            triggers = set(self._get_triggers(conn))
            expected_triggers = {
                "trg_marriages_ordering",
                "trg_marriages_bigamy",
                "trg_marriages_parent_child",
                "trg_children_self",
                "trg_children_reverse",
                "trg_children_spouse",
            }
            self.assertEqual(triggers, expected_triggers)
        finally:
            conn.close()

        self.assertEqual(len(self._get_backups()), 0)

    # 2. Legacy fixture migration
    def test_legacy_fixture_migration(self):
        # Build legacy fixture
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA user_version = 0")
        conn.execute("CREATE TABLE rp_types (guild_id INTEGER, type TEXT, PRIMARY KEY (guild_id, type))")
        conn.execute(
            """
            CREATE TABLE roleplay_entries (
                user_id INTEGER,
                guild_id INTEGER,
                type TEXT,
                url TEXT,
                texts TEXT,
                action_texts TEXT
            )
            """
        )
        # Positive control: assert fixture really lacks case_type
        table_info = conn.execute("PRAGMA table_info(roleplay_entries)")
        cols = {row[1] for row in table_info.fetchall()}
        self.assertNotIn("case_type", cols)

        conn.execute("INSERT INTO rp_types VALUES (123, 'hug')")
        conn.execute("INSERT INTO roleplay_entries VALUES (1, 123, 'hug', 'http://a', 't1', 'a1')")
        conn.execute("INSERT INTO roleplay_entries VALUES (2, 123, 'hug', 'http://b', 't2', 'a2')")

        # rp_self_cases legacy table
        conn.execute("CREATE TABLE rp_self_cases (guild_id INTEGER, type TEXT, url TEXT, texts TEXT, action_texts TEXT)")
        conn.execute("INSERT INTO rp_self_cases VALUES (123, 'hug', 'http://s', 'st', 'sa')")

        # children legacy table with parent_id unique index
        conn.execute("CREATE TABLE children (offspring_id INTEGER PRIMARY KEY, child_id INTEGER, parent_id INTEGER UNIQUE, adoption_date TEXT)")
        conn.execute("INSERT INTO children VALUES (1, 10, 5, '2020-01-01')")

        # marriages legacy table lacking single-column unique indexes, with bigamy (1,5), (5,9)
        conn.execute("CREATE TABLE marriages (marriage_id INTEGER PRIMARY KEY, spouse1_id INTEGER, spouse2_id INTEGER, marriage_date TEXT)")
        conn.execute("INSERT INTO marriages VALUES (1, 1, 5, '2020-01-01')")
        conn.execute("INSERT INTO marriages VALUES (2, 5, 9, '2020-01-01')")
        conn.commit()
        conn.close()

        applied = run_migrations(self.db_path, self.schema_sql)
        self.assertEqual(applied, [1, 2])

        backups = self._get_backups()
        self.assertEqual(len(backups), 1)
        backup_path = os.path.join(self.temp_dir.name, backups[0])

        # Verify backup has legacy layout (no case_type), rp_self_cases (1 row), marriages count 2, children count 1
        b_conn = sqlite3.connect(backup_path)
        b_info = b_conn.execute("PRAGMA table_info(roleplay_entries)")
        b_cols = {row[1] for row in b_info.fetchall()}
        self.assertNotIn("case_type", b_cols)
        self.assertEqual(b_conn.execute("SELECT count(*) FROM roleplay_entries").fetchone()[0], 2)
        self.assertEqual(b_conn.execute("SELECT count(*) FROM rp_self_cases").fetchone()[0], 1)
        self.assertEqual(b_conn.execute("SELECT count(*) FROM marriages").fetchone()[0], 2)
        self.assertEqual(b_conn.execute("SELECT count(*) FROM children").fetchone()[0], 1)
        b_conn.close()

        # Verify migrated DB
        m_conn = sqlite3.connect(self.db_path)
        m_info = m_conn.execute("PRAGMA table_info(roleplay_entries)")
        m_cols = {row[1] for row in m_info.fetchall()}
        self.assertIn("case_type", m_cols)

        # table rp_self_cases absent from sqlite_master
        self.assertIsNone(m_conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rp_self_cases'").fetchone())

        # selfcase row has url 'http://s', texts 'st', action_texts 'sa'
        self_row = m_conn.execute("SELECT url, texts, action_texts FROM roleplay_entries WHERE case_type='selfcase'").fetchone()
        self.assertEqual(self_row, ('http://s', 'st', 'sa'))

        # selfcase folded in with user_id 0
        s_cur = m_conn.execute("SELECT count(*) FROM roleplay_entries WHERE case_type='selfcase' AND user_id=0")
        self.assertEqual(s_cur.fetchone()[0], 1)

        # bigamy rows preserved (count 2)
        m_cur = m_conn.execute("SELECT count(*) FROM marriages")
        self.assertEqual(m_cur.fetchone()[0], 2)

        # children has a UNIQUE index on exactly [child_id] and NOT on [parent_id]
        self.assertTrue(self._has_single_column_unique_index(m_conn, "children", "child_id"))
        self.assertFalse(self._has_single_column_unique_index(m_conn, "children", "parent_id"))

        # marriages has UNIQUE single-column indexes on spouse1_id AND on spouse2_id
        self.assertTrue(self._has_single_column_unique_index(m_conn, "marriages", "spouse1_id"))
        self.assertTrue(self._has_single_column_unique_index(m_conn, "marriages", "spouse2_id"))

        # roleplay_entries count of case_type='standard' is 2
        std_count = m_conn.execute("SELECT count(*) FROM roleplay_entries WHERE case_type='standard'").fetchone()[0]
        self.assertEqual(std_count, 2)

        # no table named *_legacy
        t_cur = m_conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_legacy'")
        self.assertEqual(len(t_cur.fetchall()), 0)

        # user_version == 2 and 6 triggers
        self.assertEqual(m_conn.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(len(self._get_triggers(m_conn)), 6)
        m_conn.close()

    # 3. Gating
    def test_gating(self):
        applied1 = run_migrations(self.db_path, self.schema_sql)
        self.assertEqual(applied1, [1, 2])
        backups1 = self._get_backups()

        applied2 = run_migrations(self.db_path, self.schema_sql)
        self.assertEqual(applied2, [])
        backups2 = self._get_backups()
        self.assertEqual(backups1, backups2)

    # 4. Current-layout DB
    def test_current_layout_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA user_version = 0")
        conn.executescript(self.schema_sql)
        conn.execute("INSERT INTO rp_types VALUES (1, 'wave')")
        conn.commit()
        conn.close()

        applied = run_migrations(self.db_path, self.schema_sql)
        self.assertEqual(applied, [1, 2])
        backups = self._get_backups()
        self.assertEqual(len(backups), 1)

        conn = sqlite3.connect(self.db_path)
        self.assertEqual(conn.execute("SELECT count(*) FROM rp_types").fetchone()[0], 1)
        conn.close()

    # 5. Atomicity
    def test_atomicity(self):
        run_migrations(self.db_path, self.schema_sql)
        # first run on fresh DB makes 0 backups
        self.assertEqual(len(self._get_backups()), 0)

        def bad_migration_3(conn):
            conn.execute("CREATE TABLE x (a)")
            raise RuntimeError("fail")

        next_v = _next_version()
        patched_migrations = list(MIGRATIONS) + [(next_v, bad_migration_3)]

        with patch("migrations.MIGRATIONS", patched_migrations):
            with self.assertRaises(RuntimeError):
                run_migrations(self.db_path, self.schema_sql)

        # exactly 1 backup file after the failed v3 attempt
        self.assertEqual(len(self._get_backups()), 1)

        conn = sqlite3.connect(self.db_path)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='x'")
        self.assertIsNone(cur.fetchone())
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 2)
        self.assertEqual(len(self._get_triggers(conn)), 6)
        conn.close()

        def good_migration_3(conn):
            conn.execute("CREATE TABLE y (a)")

        patched_migrations_good = list(MIGRATIONS) + [(next_v, good_migration_3)]

        with patch("migrations.MIGRATIONS", patched_migrations_good):
            applied = run_migrations(self.db_path, self.schema_sql)
            self.assertEqual(applied, [next_v])

        # exactly 2 after the successful retry
        self.assertEqual(len(self._get_backups()), 2)

        conn = sqlite3.connect(self.db_path)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], next_v)
        self.assertIsNotNone(conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='y'").fetchone())
        conn.close()

    # 6. Backup failure is fail-closed
    def test_backup_failure_fail_closed(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA user_version = 0")
        conn.execute("CREATE TABLE roleplay_entries (user_id INTEGER)")
        conn.commit()
        conn.close()

        with patch("migrations._backup_database", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                run_migrations(self.db_path, self.schema_sql)

        conn = sqlite3.connect(self.db_path)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 0)
        table_info = conn.execute("PRAGMA table_info(roleplay_entries)")
        cols = {row[1] for row in table_info.fetchall()}
        self.assertNotIn("case_type", cols)
        conn.close()

    # 7. split_statements
    def test_split_statements(self):
        stmts = split_statements(INTEGRITY_TRIGGERS_SQL)
        self.assertEqual(len(stmts), 12)
        for s in stmts:
            self.assertTrue(s.startswith("DROP TRIGGER") or s.startswith("CREATE TRIGGER"))

        conn = sqlite3.connect(self.db_path)
        conn.executescript(self.schema_sql)
        for s in stmts:
            conn.execute(s)
        self.assertEqual(len(self._get_triggers(conn)), 6)
        conn.close()

    # 8. Rename-rewrite regression
    def test_rename_rewrite_regression(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA user_version = 0")
        conn.executescript(self.schema_sql)
        conn.executescript(INTEGRITY_TRIGGERS_SQL)
        
        conn.execute("DROP TABLE marriages")
        conn.execute(
            """
            CREATE TABLE marriages (
                marriage_id INTEGER PRIMARY KEY,
                spouse1_id INTEGER,
                spouse2_id INTEGER,
                marriage_date TEXT,
                UNIQUE (spouse1_id, spouse2_id)
            )
            """
        )
        conn.commit()

        # Positive control before run_migrations: marriages table has no unique single-column index, and trg_children_spouse exists
        self.assertFalse(self._has_single_column_unique_index(conn, "marriages", "spouse1_id"))
        self.assertFalse(self._has_single_column_unique_index(conn, "marriages", "spouse2_id"))
        self.assertIn("trg_children_spouse", self._get_triggers(conn))
        conn.close()

        applied = run_migrations(self.db_path, self.schema_sql)
        self.assertEqual(applied, [1, 2])

        conn = sqlite3.connect(self.db_path)
        cur = conn.execute("SELECT sql FROM sqlite_master WHERE type='trigger'")
        for row in cur.fetchall():
            self.assertNotIn("_legacy", row[0])

        conn.execute("INSERT INTO rp_types VALUES (1, 't')")
        conn.execute("INSERT INTO children (child_id, parent_id) VALUES (10, 20)")
        conn.execute("INSERT INTO marriages (spouse1_id, spouse2_id) VALUES (2, 3)")
        conn.commit()
        conn.close()

    # 9. Newer DB
    def test_newer_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA user_version = 99")
        conn.commit()
        conn.close()

        with self.assertRaises(RuntimeError):
            run_migrations(self.db_path, self.schema_sql)

        conn = sqlite3.connect(self.db_path)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 99)
        conn.close()

    # 10. test_trigger_drops_protect_later_migration
    def test_trigger_drops_protect_later_migration(self):
        run_migrations(self.db_path, self.schema_sql)

        def mig3(conn):
            conn.execute("ALTER TABLE marriages RENAME TO marriages_old")
            conn.execute(
                """
                CREATE TABLE marriages (
                    marriage_id INTEGER PRIMARY KEY,
                    spouse1_id INTEGER UNIQUE NOT NULL,
                    spouse2_id INTEGER UNIQUE NOT NULL,
                    marriage_date TEXT,
                    UNIQUE (spouse1_id, spouse2_id)
                )
                """
            )
            conn.execute("DROP TABLE marriages_old")
            conn.execute("INSERT INTO children (child_id, parent_id) VALUES (50, 60)")

        next_v = _next_version()
        patched_migrations = list(MIGRATIONS) + [(next_v, mig3)]

        with patch("migrations.MIGRATIONS", patched_migrations):
            applied = run_migrations(self.db_path, self.schema_sql)
            self.assertEqual(applied, [next_v])

        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT child_id, parent_id FROM children WHERE child_id = 50").fetchone()
        self.assertEqual(row, (50, 60))

        cur = conn.execute("SELECT sql FROM sqlite_master WHERE type='trigger'")
        for r in cur.fetchall():
            if r[0]:
                self.assertNotIn("_old", r[0])

        self.assertEqual(len(self._get_triggers(conn)), 6)
        self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], next_v)
        conn.close()


if __name__ == "__main__":
    unittest.main()
