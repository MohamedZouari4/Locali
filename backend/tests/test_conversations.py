"""Tests for the conversation history routes: list, open, rename and delete."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.main import app
from app.core.security import API_TOKEN
from app.db import database


class ConversationRoutesTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="conversations_test_")
        self._patches = [
            patch.object(database, "DB_PATH", os.path.join(self.tmpdir, "assistant_test.db")),
            patch.object(database, "_initialized", False),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(app, headers={"Authorization": f"Bearer {API_TOKEN}"})

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _chat(self, question, answer, conversation_id=None, sources=None, complete=True):
        conversation_id, reply_id = database.begin_turn(conversation_id, question)
        database.finish_turn(reply_id, answer, sources, complete=complete)
        return conversation_id

    def test_list_shows_the_most_recently_active_conversation_first(self):
        first = self._chat("first question", "a")
        second = self._chat("second question", "b")
        self._chat("follow-up", "c", conversation_id=first)

        listed = self.client.get("/conversations").json()

        self.assertEqual([c["id"] for c in listed], [first, second])
        self.assertEqual(listed[0]["title"], "first question")
        self.assertEqual(listed[0]["message_count"], 4)

    def test_open_returns_the_messages_in_order_with_their_status(self):
        conv_id = self._chat("summarize my notes", "Your notes cover", sources=["notes.md"], complete=False)

        opened = self.client.get(f"/conversations/{conv_id}").json()

        self.assertEqual(opened["title"], "summarize my notes")
        self.assertEqual(
            [(m["role"], m["content"], m["sources"], m["status"]) for m in opened["messages"]],
            [("user", "summarize my notes", [], "complete"), ("assistant", "Your notes cover", ["notes.md"], "incomplete")],
        )

    def test_rename_changes_the_title(self):
        conv_id = self._chat("hello", "hi")

        renamed = self.client.patch(f"/conversations/{conv_id}", json={"title": "  Greetings  "})

        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["title"], "Greetings")
        self.assertEqual(self.client.get("/conversations").json()[0]["title"], "Greetings")

    def test_rename_rejects_an_empty_title(self):
        conv_id = self._chat("hello", "hi")

        self.assertEqual(self.client.patch(f"/conversations/{conv_id}", json={"title": ""}).status_code, 422)

    def test_delete_removes_the_conversation_and_its_messages(self):
        conv_id = self._chat("hello", "hi")
        kept = self._chat("other", "chat")

        self.assertEqual(self.client.delete(f"/conversations/{conv_id}").status_code, 204)

        self.assertEqual([c["id"] for c in self.client.get("/conversations").json()], [kept])
        self.assertEqual(database.get_messages(conv_id), [])
        self.assertEqual(len(database.get_messages(kept)), 2)

    def test_unknown_conversation_returns_404(self):
        for response in (
            self.client.get("/conversations/missing"),
            self.client.patch("/conversations/missing", json={"title": "x"}),
            self.client.delete("/conversations/missing"),
        ):
            self.assertEqual(response.status_code, 404)

    def test_routes_require_the_token(self):
        self.assertEqual(TestClient(app).get("/conversations").status_code, 401)

    def test_chats_survive_a_restart(self):
        conv_id = self._chat("hello", "hi")
        database._initialized = False  # the next connection runs startup again, like a restarted server

        opened = self.client.get(f"/conversations/{conv_id}").json()

        self.assertEqual([m["content"] for m in opened["messages"]], ["hello", "hi"])

    def test_openapi_documents_the_routes(self):
        paths = self.client.get("/openapi.json").json()["paths"]

        self.assertEqual(set(paths["/conversations"]), {"get"})
        self.assertEqual(set(paths["/conversations/{conversation_id}"]), {"get", "patch", "delete"})
