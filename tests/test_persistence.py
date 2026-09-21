import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import app.database as database
import app.tool.tools as tools


class PersistenceTestCase(unittest.TestCase):
    def setUp(self):
        # Create a temporary folder for this test run so the database and log file
        # do not interfere with the real project files.
        self.tmpdir = tempfile.mkdtemp(prefix="persistence_test_")
        self.db_path = os.path.join(self.tmpdir, "assistant_test.db")
        self.log_file = os.path.join(self.tmpdir, "logs", "actions.log")

        # Point the app modules at the temporary database/log paths for isolated testing.
        self._patches = [
            patch.object(database, "DB_PATH", self.db_path),
            patch.object(database, "_initialized", False),
            patch.object(tools, "ALLOWED_ROOT", self.tmpdir),
            patch.object(tools, "LOG_FILE", self.log_file),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        # Stop the patches and remove the temporary test directory.
        for p in self._patches:
            p.stop()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_conversation_history_is_persisted(self):
        # Create a conversation, save user and assistant messages, then read them back.
        conv_id = database.create_conversation(title="persistence-test")
        database.save_conversation(conv_id, "user", "hello")
        database.save_conversation(conv_id, "assistant", "hi")

        messages = database.get_messages(conv_id)

        # Verify the saved messages are returned in the expected order and content.
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[0]["content"], "hello")
        self.assertEqual(messages[1]["role"], "assistant")
        self.assertEqual(messages[1]["content"], "hi")

    def test_audit_log_entries_are_written_to_db(self):
        # Trigger logging and confirm the action is stored in the audit_log table.
        tools._log("manual audit test")

        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT action, success FROM audit_log ORDER BY id DESC LIMIT 1"
            ).fetchall()
        finally:
            conn.close()

        # Check that the latest audit entry matches the action we just logged.
        self.assertTrue(rows)
        self.assertEqual(rows[0][0], "manual audit test")
        self.assertEqual(rows[0][1], 1)


if __name__ == "__main__":
    unittest.main()
