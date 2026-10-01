"""Tests that conversations and file-tool audit entries are saved to SQLite,
using a temporary database and log file.
"""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.ai.chat import orchestrator
from app.db import database
from app.services import chat_service
from app.tools import audit_log, file_tools


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
            patch.object(file_tools, "ALLOWED_ROOT", self.tmpdir),
            patch.object(audit_log, "LOG_FILE", self.log_file),
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
        audit_log.log_action("manual audit test")

        rows = self._audit_rows()

        # Check that the latest audit entry matches the action we just logged.
        self.assertTrue(rows)
        self.assertEqual(rows[0][0], "manual audit test")
        self.assertEqual(rows[0][2], 1)

    def _audit_rows(self):
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute("SELECT action, target_path, success FROM audit_log ORDER BY id DESC").fetchall()
        finally:
            conn.close()

    def test_audit_log_records_the_target_path(self):
        file_tools.create_folder("reports")

        action, target_path, success = self._audit_rows()[0]
        self.assertEqual(target_path, "reports")
        self.assertEqual(success, 1)

    def test_blocked_tool_call_is_audited_as_a_failure(self):
        tool_call = {"function": {"name": "move_file", "arguments": {"src": "../outside.txt", "dst": "x.txt"}}}
        orchestrator._run_tool_calls([tool_call], [])

        action, _target_path, success = self._audit_rows()[0]
        self.assertTrue(action.startswith("blocked move_file"))
        self.assertEqual(success, 0)

    def test_chat_service_starts_and_continues_a_conversation(self):
        reply = self._chat_reply({"role": "assistant", "content": "hi there"})
        with patch.object(orchestrator.requests, "post", return_value=reply):
            first = chat_service.get_answer("hello")
            second = chat_service.get_answer("again", conversation_id=first["conversation_id"])

        self.assertEqual(first["conversation_id"], second["conversation_id"])
        self.assertEqual(len(database.get_messages(first["conversation_id"])), 4)

    def _chat_reply(self, message):
        reply = Mock()
        reply.json.return_value = {"message": message}
        return reply

    def test_ask_saves_a_normal_answer(self):
        conv_id = database.create_conversation(title="ask-test")
        reply = self._chat_reply({"role": "assistant", "content": "hi there"})
        with patch.object(orchestrator.requests, "post", return_value=reply):
            result = orchestrator.ask("hello", conversation_id=conv_id)

        self.assertEqual(result, ("hi there", [], False))
        saved = [(m["role"], m["content"]) for m in database.get_messages(conv_id)]
        self.assertEqual(saved, [("user", "hello"), ("assistant", "hi there")])

    def test_ask_returns_three_values_at_the_tool_call_limit(self):
        conv_id = database.create_conversation(title="ask-limit-test")
        tool_call = {"function": {"name": "no_such_tool", "arguments": {}}}
        reply = self._chat_reply({"role": "assistant", "content": "", "tool_calls": [tool_call]})
        with patch.object(orchestrator.requests, "post", return_value=reply):
            answer, _sources, used_tools = orchestrator.ask("do something", conversation_id=conv_id)

        self.assertIn("tool-call limit", answer)
        self.assertTrue(used_tools)
        self.assertEqual(len(database.get_messages(conv_id)), 2)


if __name__ == "__main__":
    unittest.main()
