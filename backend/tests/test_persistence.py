"""Tests that conversations and file-tool audit entries are saved to SQLite,
using a temporary database and log file.
"""

import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from fastapi.testclient import TestClient

from app.ai.chat import orchestrator
from app.api.main import app
from app.core.security import API_TOKEN
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

    def _saved(self, conv_id):
        return [(m["role"], m["content"], m["status"]) for m in database.get_messages(conv_id)]

    def test_a_turn_stores_both_messages_before_and_after_the_reply(self):
        conv_id, reply_id = database.begin_turn(None, "hello")
        self.assertEqual(self._saved(conv_id), [("user", "hello", "complete"), ("assistant", "", "streaming")])

        database.finish_turn(reply_id, "hi", ["notes.md"])
        self.assertEqual(self._saved(conv_id), [("user", "hello", "complete"), ("assistant", "hi", "complete")])
        self.assertEqual(database.get_messages(conv_id)[1]["sources"], '["notes.md"]')

    def test_a_complete_reply_is_never_downgraded(self):
        conv_id, reply_id = database.begin_turn(None, "hello")
        database.finish_turn(reply_id, "hi")
        database.finish_turn(reply_id, "h", complete=False)  # a cleanup path running afterwards

        self.assertEqual(self._saved(conv_id)[1], ("assistant", "hi", "complete"))

    def test_an_unknown_conversation_id_starts_a_new_conversation(self):
        conv_id, _ = database.begin_turn("does-not-exist", "hello")

        self.assertNotEqual(conv_id, "does-not-exist")
        self.assertEqual(database.list_conversations()[0]["title"], "hello")

    def test_replies_left_streaming_by_a_crash_are_marked_incomplete_on_startup(self):
        conv_id, _ = database.begin_turn(None, "hello")
        database._initialized = False  # the next connection runs startup again, like a restarted server
        database.get_connection().close()

        self.assertEqual(self._saved(conv_id)[1], ("assistant", "", "incomplete"))

    def test_an_old_database_gets_the_status_column(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, started_at TIMESTAMP, title TEXT)")
        conn.execute(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL,"
            " role TEXT NOT NULL, content TEXT NOT NULL, sources TEXT, created_at TIMESTAMP)"
        )
        conn.execute("INSERT INTO conversations (id) VALUES ('old')")
        conn.execute("INSERT INTO messages (conversation_id, role, content) VALUES ('old', 'user', 'hi')")
        conn.commit()
        conn.close()

        self.assertEqual(self._saved("old"), [("user", "hi", "complete")])

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

    def test_chat_service_saves_a_normal_answer(self):
        reply = self._chat_reply({"role": "assistant", "content": "hi there"})
        with patch.object(orchestrator.requests, "post", return_value=reply):
            result = chat_service.get_answer("hello")

        self.assertEqual(result["response"], "hi there")
        self.assertEqual(self._saved(result["conversation_id"]), [("user", "hello", "complete"), ("assistant", "hi there", "complete")])

    def test_chat_service_saves_the_tool_call_limit_message(self):
        tool_call = {"function": {"name": "no_such_tool", "arguments": {}}}
        reply = self._chat_reply({"role": "assistant", "content": "", "tool_calls": [tool_call]})
        with patch.object(orchestrator.requests, "post", return_value=reply):
            result = chat_service.get_answer("do something")

        self.assertIn("tool-call limit", result["response"])
        self.assertTrue(result["used_tools"])
        self.assertEqual(len(database.get_messages(result["conversation_id"])), 2)

    def test_chat_service_stores_a_failed_answer_as_incomplete(self):
        with (
            patch.object(orchestrator.requests, "post", side_effect=ConnectionError("Ollama is down")),
            self.assertRaises(ConnectionError),
        ):
            chat_service.get_answer("hello")

        conv_id = database.list_conversations()[0]["id"]
        self.assertEqual(self._saved(conv_id), [("user", "hello", "complete"), ("assistant", "", "incomplete")])

    def _stream_turn(self, lines):
        # Streams one answer over the real WebSocket route, with Ollama replaced by `lines`.
        reply = MagicMock()
        reply.__enter__.return_value = reply
        reply.iter_lines.return_value = lines
        with patch.object(orchestrator.requests, "post", return_value=reply):
            with TestClient(app).websocket_connect("/chat/stream", headers={"authorization": f"Bearer {API_TOKEN}"}) as ws:
                ws.send_json({"message": "hello", "use_docs": False})
                events = [ws.receive_json()]
                while events[-1]["type"] not in ("done", "error"):
                    events.append(ws.receive_json())
        return events, database.list_conversations()[0]["id"]

    def test_streamed_answer_is_stored_complete(self):
        events, conv_id = self._stream_turn(
            [
                json.dumps({"message": {"content": "hi "}, "done": False}).encode(),
                json.dumps({"message": {"content": "there"}, "done": True}).encode(),
            ]
        )

        self.assertEqual(events[-1], {"type": "done", "conversation_id": conv_id})
        self.assertEqual(self._saved(conv_id), [("user", "hello", "complete"), ("assistant", "hi there", "complete")])

    def test_stream_cut_off_mid_answer_is_stored_incomplete(self):
        def lines():
            yield json.dumps({"message": {"content": "partial "}, "done": False}).encode()
            raise ConnectionError("Ollama stopped")

        events, conv_id = self._stream_turn(lines())

        self.assertEqual([event["type"] for event in events], ["token", "error"])
        self.assertEqual(self._saved(conv_id), [("user", "hello", "complete"), ("assistant", "partial ", "incomplete")])


if __name__ == "__main__":
    unittest.main()
