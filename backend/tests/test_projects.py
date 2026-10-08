"""Tests for storing projects, their folders and their conversations, on a temporary database."""

import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.db import database


class ProjectStoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="projects_test_")
        self._patches = [
            patch.object(database, "DB_PATH", os.path.join(self.tmpdir, "assistant_test.db")),
            patch.object(database, "_initialized", False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_a_project_with_two_folders_is_stored_and_reloaded(self):
        created = database.create_project("Thesis", "Answer in French.", [("D:/Thesis/notes", "read"), ("D:/Thesis/drafts", "act")])

        reloaded = database.get_project(created["id"])

        self.assertEqual((reloaded["name"], reloaded["instructions"]), ("Thesis", "Answer in French."))
        folders = [(f["path"], f["permission"]) for f in reloaded["folders"]]
        self.assertEqual(folders, [("D:/Thesis/drafts", "act"), ("D:/Thesis/notes", "read")])

    def test_an_unknown_permission_stores_nothing(self):
        with self.assertRaises(sqlite3.IntegrityError):
            database.create_project("Thesis", folders=[("D:/a", "read"), ("D:/b", "write")])

        self.assertEqual(database.list_projects(), [])

    def test_project_names_are_unique_ignoring_case(self):
        database.create_project("Thesis")

        with self.assertRaises(sqlite3.IntegrityError):
            database.create_project("thesis")

    def test_a_conversation_can_be_started_in_a_project(self):
        project = database.create_project("Thesis")

        in_project, _ = database.begin_turn(None, "hello", project_id=project["id"])
        outside, _ = database.begin_turn(None, "hi")

        self.assertEqual(database.get_conversation(in_project)["project_id"], project["id"])
        self.assertIsNone(database.get_conversation(outside)["project_id"])

    def test_deleting_a_project_removes_its_folders_and_keeps_its_conversations(self):
        project = database.create_project("Thesis", folders=[("D:/a", "read")])
        conversation_id, _ = database.begin_turn(None, "hello", project_id=project["id"])

        with database._transaction() as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (project["id"],))

        self.assertIsNone(database.get_project(project["id"]))
        self.assertIsNone(database.get_conversation(conversation_id)["project_id"])
        with database._transaction() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM project_folders").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
