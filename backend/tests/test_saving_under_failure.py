"""Stops the model mid-answer in different ways and checks that the conversation is still saved:
the user message, the assistant reply marked incomplete with whatever text arrived, and the
conversation in the conversation list. Ollama is faked, so this runs without it (and in CI).
"""

import json
import os
import shutil
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

import requests
from fastapi.testclient import TestClient

from app.ai.chat import orchestrator
from app.api.main import app
from app.core.security import API_TOKEN
from app.db import database


def _token(text):
    return json.dumps({"message": {"content": text}, "done": False}).encode()


def _ollama(lines):
    # A fake streaming reply from Ollama's /api/chat that yields `lines`.
    reply = MagicMock()
    reply.__enter__.return_value = reply
    reply.iter_lines.return_value = lines
    return reply


class SavingUnderFailureTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="saving_failure_test_")
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

    def _chat(self, ollama, leave_after_first_token=False, release=None):
        # Asks one question over /chat/stream and returns the event types the client received.
        with patch.object(orchestrator.requests, "post", **ollama):
            with TestClient(app).websocket_connect("/chat/stream", headers={"authorization": f"Bearer {API_TOKEN}"}) as ws:
                ws.send_json({"message": "summarize my notes", "use_docs": False})
                events = [ws.receive_json()["type"]]
                if leave_after_first_token:
                    ws.close()  # the user closed the app or clicked Stop
                    release.set()  # let the model carry on; the server notices on its next send
                else:
                    while events[-1] not in ("done", "error"):
                        events.append(ws.receive_json()["type"])
        return events

    def _assert_saved_incomplete(self, reply_text):
        conversations = database.list_conversations()
        self.assertEqual(len(conversations), 1)
        self.assertEqual(conversations[0]["title"], "summarize my notes")

        messages = database.get_messages(conversations[0]["id"])
        self.assertEqual([(m["role"], m["status"]) for m in messages], [("user", "complete"), ("assistant", "incomplete")])
        self.assertEqual(messages[0]["content"], "summarize my notes")
        self.assertTrue(messages[1]["content"].startswith(reply_text), messages[1]["content"])

    def test_model_fails_mid_answer(self):
        def lines():
            yield _token("Your notes ")
            yield _token("cover ")
            raise requests.ConnectionError("Ollama stopped")

        events = self._chat({"return_value": _ollama(lines())})

        self.assertEqual(events, ["token", "token", "error"])
        self._assert_saved_incomplete("Your notes cover ")

    def test_model_fails_before_the_first_token(self):
        failing = _ollama([])
        failing.raise_for_status.side_effect = requests.HTTPError("500 Server Error")

        events = self._chat({"return_value": failing})

        self.assertEqual(events, ["error"])
        self._assert_saved_incomplete("")

    def test_model_is_unreachable(self):
        events = self._chat({"side_effect": requests.ConnectionError("connection refused")})

        self.assertEqual(events, ["error"])
        self._assert_saved_incomplete("")

    def test_client_leaves_mid_answer(self):
        release = threading.Event()

        def lines():
            yield _token("Your notes ")
            release.wait(timeout=5)  # still generating when the client leaves
            yield from (_token("cover ") for _ in range(20))

        events = self._chat({"return_value": _ollama(lines())}, leave_after_first_token=True, release=release)

        self.assertEqual(events, ["token"])
        self._assert_saved_incomplete("Your notes ")


if __name__ == "__main__":
    unittest.main()
