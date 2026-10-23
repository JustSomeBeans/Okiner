"""
Standalone database migrations module.

Note: Indexes must NOT be in rp_schema.sql (put them in a later migration)
because the schema runs before pending migrations on legacy DBs.
Any future migration that rebuilds roleplay_entries must recreate this index.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Callable

import database


def split_statements(script: str) -> list[str]:
    """Split SQL script into individual statements using sqlite3.complete_statement."""
    statements = []
    current_lines = []
    for line in script.splitlines():
        current_lines.append(line)
        candidate = "\n".join(current_lines)
        if sqlite3.complete_statement(candidate):
            statements.append(candidate.strip())
            current_lines = []
    remainder = "\n".join(current_lines).strip()
    if remainder:
        statements.append(remainder)
    return [s for s in statements if s and not s.startswith("--")]


def _backup_database(conn: sqlite3.Connection, db_path: str) -> str:
    """Backup database using sqlite3 backup API and verify integrity."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = f"{db_path}.bak-{timestamp}"
    counter = 2
    while os.path.exists(backup_path):
        backup_path = f"{db_path}.bak-{timestamp}-{counter}"
        counter += 1

    dst = sqlite3.connect(backup_path)
    try:
        conn.backup(dst)
    finally:
        dst.close()

    chk_conn = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    try:
        cur = chk_conn.execute("PRAGMA integrity_check")
        row = cur.fetchone()
        if not row or row[0] != "ok":
            raise RuntimeError(f"Database backup integrity check failed: {row}")
    finally:
        chk_conn.close()

    return backup_path


def _migration_001_legacy_layouts(conn: sqlite3.Connection) -> None:
    """Migrate legacy table layouts to current schema structure."""
    # 1. roleplay_entries case_type rebuild
    table_info = conn.execute("PRAGMA table_info(roleplay_entries)")
    columns = {row[1] for row in table_info.fetchall()}
    if columns and "case_type" not in columns:
        conn.execute("ALTER TABLE roleplay_entries RENAME TO roleplay_entries_legacy")
        conn.execute(
            """
            CREATE TABLE roleplay_entries (
                user_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                type TEXT NOT NULL,
                case_type TEXT NOT NULL DEFAULT 'standard',
                url TEXT,
                texts TEXT,
                action_texts TEXT,
                PRIMARY KEY (user_id, guild_id, type, case_type, url, texts, action_texts),
                FOREIGN KEY (guild_id, type)
                    REFERENCES rp_types(guild_id, type)
                    ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            INSERT INTO roleplay_entries (user_id, guild_id, type, case_type, url, texts, action_texts)
            SELECT user_id, guild_id, type, 'standard', url, texts, action_texts
            FROM roleplay_entries_legacy
            """
        )
        conn.execute("DROP TABLE roleplay_entries_legacy")

    # 2. rp_self_cases fold
    legacy_self = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='rp_self_cases'"
    )
    if legacy_self.fetchone():
        conn.execute(
            """
            INSERT OR IGNORE INTO roleplay_entries
                (user_id, guild_id, type, case_type, url, texts, action_texts)
            SELECT
                0,
                guild_id,
                type,
                'selfcase',
                url,
                texts,
                action_texts
            FROM rp_self_cases
            """
        )
        conn.execute("DROP TABLE rp_self_cases")

    # 3. children table unique parent_id index rebuild
    children_table_info = conn.execute("PRAGMA table_info(children)")
    children_columns = {row[1] for row in children_table_info.fetchall()}
    children_indexes = conn.execute("PRAGMA index_list(children)")
    children_index_rows = children_indexes.fetchall()
    parent_unique = False
    for index_row in children_index_rows:
        if not index_row[2]:
            continue
        index_name = index_row[1]
        index_info = conn.execute(f"PRAGMA index_info({index_name!r})")
        indexed_columns = [row[2] for row in index_info.fetchall()]
        if indexed_columns == ["parent_id"]:
            parent_unique = True
            break
    if children_columns and parent_unique:
        conn.execute("ALTER TABLE children RENAME TO children_legacy")
        conn.execute(
            """
            CREATE TABLE children (
                offspring_id INTEGER PRIMARY KEY AUTOINCREMENT,
                child_id INTEGER UNIQUE NOT NULL,
                parent_id INTEGER NOT NULL,
                adoption_date TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO children (offspring_id, child_id, parent_id, adoption_date)
            SELECT offspring_id, child_id, parent_id, adoption_date
            FROM children_legacy
            """
        )
        conn.execute("DROP TABLE children_legacy")

    # 4. marriages table single-column unique index rebuild
    marriages_table_info = conn.execute("PRAGMA table_info(marriages)")
    marriages_columns = {row[1] for row in marriages_table_info.fetchall()}
    marriages_indexes = conn.execute("PRAGMA index_list(marriages)")
    marriages_index_rows = marriages_indexes.fetchall()
    spouse1_unique = False
    spouse2_unique = False
    for index_row in marriages_index_rows:
        if not index_row[2]:
            continue
        index_name = index_row[1]
        index_info = conn.execute(f"PRAGMA index_info({index_name!r})")
        indexed_columns = [row[2] for row in index_info.fetchall()]
        if indexed_columns == ["spouse1_id"]:
            spouse1_unique = True
        if indexed_columns == ["spouse2_id"]:
            spouse2_unique = True
    if marriages_columns and (not spouse1_unique or not spouse2_unique):
        conn.execute("ALTER TABLE marriages RENAME TO marriages_legacy")
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
        conn.execute(
            """
            INSERT INTO marriages (marriage_id, spouse1_id, spouse2_id, marriage_date)
            SELECT marriage_id, spouse1_id, spouse2_id, marriage_date
            FROM marriages_legacy
            """
        )
        conn.execute("DROP TABLE marriages_legacy")


def _migration_002_roleplay_entries_dedupe(conn: sqlite3.Connection) -> None:
    """Remove duplicate roleplay entries keeping lowest rowid and create unique content index."""
    cursor = conn.execute(
        """
        DELETE FROM roleplay_entries WHERE rowid NOT IN (
            SELECT MIN(rowid) FROM roleplay_entries
            GROUP BY guild_id, type, case_type, COALESCE(url,''), COALESCE(texts,''), COALESCE(action_texts,'')
        )
        """
    )
    logging.info("Removed %d duplicate roleplay_entries rows", cursor.rowcount)
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_roleplay_entries_content
        ON roleplay_entries(guild_id, type, case_type, COALESCE(url,''), COALESCE(texts,''), COALESCE(action_texts,''))
        """
    )


MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _migration_001_legacy_layouts),
    (2, _migration_002_roleplay_entries_dedupe),
]


def run_migrations(db_path: str, schema_sql: str) -> list[int]:
    """Run pending database migrations and install integrity triggers."""
    applied = []
    conn = sqlite3.connect(db_path, isolation_level=None)
    database.init_connection(conn)
    try:
        cur = conn.execute("PRAGMA user_version")
        current = cur.fetchone()[0]

        max_version = max([v for v, _ in MIGRATIONS]) if MIGRATIONS else 0
        if current > max_version:
            raise RuntimeError("database is newer than this code")

        pending = [(v, fn) for v, fn in MIGRATIONS if v > current]
        pending.sort(key=lambda x: x[0])

        if pending:
            cur = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
            )
            has_tables = cur.fetchone() is not None
            if has_tables:
                backup_fn = globals().get("_backup_database", _backup_database)
                backup_fn(conn, db_path)

        conn.executescript(schema_sql)

        drop_triggers_sql = """
        DROP TRIGGER IF EXISTS trg_marriages_ordering;
        DROP TRIGGER IF EXISTS trg_marriages_bigamy;
        DROP TRIGGER IF EXISTS trg_marriages_parent_child;
        DROP TRIGGER IF EXISTS trg_children_self;
        DROP TRIGGER IF EXISTS trg_children_reverse;
        DROP TRIGGER IF EXISTS trg_children_spouse;
        """

        if pending:
            for version, fn in pending:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for stmt in split_statements(drop_triggers_sql):
                        conn.execute(stmt)
                    fn(conn)
                    for stmt in split_statements(database.INTEGRITY_TRIGGERS_SQL):
                        conn.execute(stmt)
                    conn.execute(f"PRAGMA user_version = {int(version)}")
                    conn.execute("COMMIT")
                    applied.append(version)
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
        else:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for stmt in split_statements(drop_triggers_sql):
                    conn.execute(stmt)
                for stmt in split_statements(database.INTEGRITY_TRIGGERS_SQL):
                    conn.execute(stmt)
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

        return applied
    finally:
        conn.close()
