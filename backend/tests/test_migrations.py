"""Tests for the versioned schema migrations in app/db/migrations.py, each on a temporary database."""

import os
import shutil
import sqlite3
import tempfile
import unittest

from app.db import migrations

TABLES = {"conversations", "messages", "audit_log", "jobs", "indexed_folders"}


def _add_pinned(conn):
    conn.execute("ALTER TABLE conversations ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")


def _add_column_then_fail(conn):
    conn.execute("ALTER TABLE conversations ADD COLUMN broken TEXT")
    raise RuntimeError("migration failed halfway")


class MigrationsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="migrations_test_")
        self.db_path = os.path.join(self.tmpdir, "assistant_test.db")
        self.conn = sqlite3.connect(self.db_path)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _tables(self):
        return {row[0] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    def _columns(self, table):
        return {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}

    def test_a_new_column_can_be_added_without_deleting_user_data(self):
        migrations.migrate(self.conn)
        with self.conn:
            self.conn.execute("INSERT INTO conversations (id, title) VALUES ('c1', 'kept')")
            self.conn.execute("INSERT INTO messages (conversation_id, role, content) VALUES ('c1', 'user', 'hello')")

        applied = migrations.migrate(self.conn, migrations.MIGRATIONS + [_add_pinned])

        self.assertEqual(applied, [len(migrations.MIGRATIONS) + 1])
        self.assertEqual(self.conn.execute("SELECT id, title, pinned FROM conversations").fetchall(), [("c1", "kept", 0)])
        self.assertEqual(self.conn.execute("SELECT content FROM messages").fetchall(), [("hello",)])
        self.assertEqual(migrations.schema_version(self.conn), len(migrations.MIGRATIONS) + 1)

    def test_a_new_database_gets_every_table_and_the_latest_version(self):
        applied = migrations.migrate(self.conn)

        self.assertEqual(applied, list(range(1, len(migrations.MIGRATIONS) + 1)))
        self.assertTrue(TABLES <= self._tables())
        self.assertEqual(migrations.schema_version(self.conn), len(migrations.MIGRATIONS))

    def test_a_database_from_before_migrations_keeps_its_data(self):
        # Version 0 with tables already there: what every database created before migrations looks like.
        self.conn.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, started_at TIMESTAMP, title TEXT)")
        self.conn.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL,"
            " role TEXT NOT NULL, content TEXT NOT NULL, sources TEXT, created_at TIMESTAMP)"
        )
        self.conn.execute("INSERT INTO conversations (id, title) VALUES ('old', 'from before')")
        self.conn.execute("INSERT INTO messages (conversation_id, role, content) VALUES ('old', 'user', 'hi')")
        self.conn.commit()

        migrations.migrate(self.conn)

        self.assertEqual(migrations.schema_version(self.conn), len(migrations.MIGRATIONS))
        self.assertTrue(TABLES <= self._tables())
        self.assertEqual(self.conn.execute("SELECT title FROM conversations").fetchall(), [("from before",)])
        self.assertEqual(self.conn.execute("SELECT content, status FROM messages").fetchall(), [("hi", "complete")])

    def test_running_again_applies_nothing(self):
        migrations.migrate(self.conn)

        self.assertEqual(migrations.migrate(self.conn), [])
        self.assertEqual(migrations.schema_version(self.conn), len(migrations.MIGRATIONS))

    def test_a_failing_migration_leaves_the_database_unchanged(self):
        migrations.migrate(self.conn)
        version = migrations.schema_version(self.conn)

        with self.assertRaises(RuntimeError):
            migrations.migrate(self.conn, migrations.MIGRATIONS + [_add_column_then_fail])

        self.assertNotIn("broken", self._columns("conversations"))
        self.assertEqual(migrations.schema_version(self.conn), version)

    def test_a_database_from_a_newer_version_is_refused(self):
        migrations.migrate(self.conn)
        self.conn.execute("PRAGMA user_version = 99")

        with self.assertRaises(migrations.DatabaseTooNewError):
            migrations.migrate(self.conn)
        self.assertEqual(migrations.schema_version(self.conn), 99)

    def test_an_existing_database_is_backed_up_before_it_is_migrated(self):
        self.conn.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, started_at TIMESTAMP, title TEXT)")
        self.conn.execute("INSERT INTO conversations (id, title) VALUES ('old', 'from before')")
        self.conn.commit()

        migrations.migrate(self.conn, backup_path=self.db_path)

        backup = sqlite3.connect(f"{self.db_path}.v0.bak")
        try:
            self.assertEqual(backup.execute("SELECT title FROM conversations").fetchall(), [("from before",)])
            self.assertEqual(backup.execute("PRAGMA user_version").fetchone()[0], 0)
        finally:
            backup.close()

    def test_a_new_or_current_database_is_not_backed_up(self):
        migrations.migrate(self.conn, backup_path=self.db_path)  # empty file: nothing to protect
        migrations.migrate(self.conn, backup_path=self.db_path)  # already current: nothing changes

        self.assertEqual([name for name in os.listdir(self.tmpdir) if name.endswith(".bak")], [])


if __name__ == "__main__":
    unittest.main()
