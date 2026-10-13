"""Tests for the versioned schema migrations in app/db/migrations.py, each on a temporary database."""

import os
import shutil
import sqlite3
import tempfile
import unittest

from app.db import migrations

TABLES = {
    "conversations",
    "messages",
    "audit_log",
    "jobs",
    "indexed_folders",
    "projects",
    "project_folders",
    "catalog_files",
    "text_cache",
    "text_cache_parts",
    "text_search",
}


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

    def test_existing_conversations_belong_to_no_project_after_projects_are_added(self):
        migrations.migrate(self.conn, migrations.MIGRATIONS[:1])
        with self.conn:
            self.conn.execute("INSERT INTO conversations (id, title) VALUES ('c1', 'kept')")

        migrations.migrate(self.conn, migrations.MIGRATIONS[:2])

        self.assertEqual(self.conn.execute("SELECT id, title, project_id FROM conversations").fetchall(), [("c1", "kept", None)])

    def test_chats_without_a_project_move_into_general(self):
        migrations.migrate(self.conn, migrations.MIGRATIONS[:2])
        with self.conn:
            self.conn.execute("INSERT INTO conversations (id, title) VALUES ('c1', 'kept')")
            self.conn.execute("INSERT INTO messages (conversation_id, role, content) VALUES ('c1', 'user', 'hello')")

        migrations.migrate(self.conn)

        general_id = self.conn.execute("SELECT id FROM projects WHERE name = 'General'").fetchone()[0]
        self.assertEqual(self.conn.execute("SELECT id, title, project_id FROM conversations").fetchall(), [("c1", "kept", general_id)])
        self.assertEqual(self.conn.execute("SELECT content FROM messages").fetchall(), [("hello",)])

    def test_an_existing_general_project_is_reused(self):
        migrations.migrate(self.conn, migrations.MIGRATIONS[:2])
        with self.conn:
            self.conn.execute("INSERT INTO projects (id, name) VALUES ('p1', 'general')")
            self.conn.execute("INSERT INTO conversations (id, title) VALUES ('c1', 'kept')")

        migrations.migrate(self.conn)

        self.assertEqual(self.conn.execute("SELECT id FROM projects").fetchall(), [("p1",)])
        self.assertEqual(self.conn.execute("SELECT project_id FROM conversations").fetchall(), [("p1",)])

    def test_general_is_not_created_without_old_chats(self):
        migrations.migrate(self.conn)

        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 0)

    def test_the_catalog_is_added_empty_and_existing_projects_are_kept(self):
        migrations.migrate(self.conn, migrations.MIGRATIONS[:3])
        with self.conn:
            self.conn.execute("INSERT INTO projects (id, name) VALUES ('p1', 'Thesis')")
            self.conn.execute("INSERT INTO conversations (id, title, project_id) VALUES ('c1', 'kept', 'p1')")

        migrations.migrate(self.conn)

        self.assertEqual(self.conn.execute("SELECT id, name FROM projects").fetchall(), [("p1", "Thesis")])
        self.assertEqual(self.conn.execute("SELECT project_id FROM conversations").fetchall(), [("p1",)])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM catalog_files").fetchone()[0], 0)

    def test_projects_get_empty_ignore_patterns_and_no_skipped_counts(self):
        migrations.migrate(self.conn, migrations.MIGRATIONS[:4])
        with self.conn:
            self.conn.execute("INSERT INTO projects (id, name) VALUES ('p1', 'Thesis')")

        migrations.migrate(self.conn)

        self.assertEqual(
            self.conn.execute("SELECT name, ignore_patterns, catalog_skipped FROM projects").fetchall(), [("Thesis", "[]", None)]
        )

    def test_catalog_files_keep_their_rows_and_start_without_text(self):
        """P1-E3-T1: migration 6 adds the text cache to a database that already has a catalog."""
        migrations.migrate(self.conn, migrations.MIGRATIONS[:5])
        with self.conn:
            self.conn.execute("INSERT INTO projects (id, name) VALUES ('p1', 'Thesis')")
            self.conn.execute(
                "INSERT INTO catalog_files (project_id, file_key, path, name, extension, size, file_modified_at)"
                " VALUES ('p1', 'path:a', 'C:/docs/a.txt', 'a.txt', 'txt', 5, '2026-10-12 10:00:00')"
            )

        migrations.migrate(self.conn)

        self.assertEqual(self.conn.execute("SELECT name, text_hash FROM catalog_files").fetchall(), [("a.txt", None)])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM text_cache").fetchone()[0], 0)

    def test_text_already_cached_keeps_its_parts_and_becomes_searchable(self):
        """P1-E3-T3: migration 7 rebuilds text_cache_parts with an id and indexes the text already cached."""
        migrations.migrate(self.conn, migrations.MIGRATIONS[:6])
        with self.conn:
            self.conn.execute("INSERT INTO text_cache (content_hash, extension, extractor_version, unit) VALUES ('h1', 'pdf', 2, 'page')")
            self.conn.execute(
                "INSERT INTO text_cache_parts (cache_id, part, text) VALUES (1, 1, 'cover page'), (1, 2, 'quarterly tax report')"
            )

        migrations.migrate(self.conn)

        parts = self.conn.execute("SELECT cache_id, part, text FROM text_cache_parts ORDER BY part").fetchall()
        self.assertEqual(parts, [(1, 1, "cover page"), (1, 2, "quarterly tax report")])
        found = self.conn.execute(
            "SELECT p.part FROM text_search JOIN text_cache_parts p ON p.id = text_search.rowid WHERE text_search MATCH ?",
            ('"tax report"',),
        ).fetchall()
        self.assertEqual(found, [(2,)])

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
