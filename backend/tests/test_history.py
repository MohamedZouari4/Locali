"""Tests for chat history (P1-E5-T2): the model gets the conversation's earlier questions and answers, newest
last and capped, never from another project, and a restart doesn't lose them. Uses a temporary database; no
model is called, the request to Ollama is captured."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.ai.chat import orchestrator
from app.db import database
from app.services import chat_service


class HistoryTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = os.path.realpath(tempfile.mkdtemp(prefix="history_test_"))
        self._patches = [
            patch.object(database, "DB_PATH", os.path.join(self.tmpdir, "assistant_test.db")),
            patch.object(database, "_initialized", False),
        ]
        for p in self._patches:
            p.start()
        self.project_id = database.create_project("A")["id"]

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _turn(self, conversation_id, question, answer, project_id=None):
        conversation_id, reply_id = chat_service.begin_turn(project_id or self.project_id, conversation_id, question)
        database.finish_turn(reply_id, answer)
        return conversation_id


class HistoryTests(HistoryTestCase):
    def test_earlier_turns_come_back_oldest_first_and_capped(self):
        conversation_id = self._turn(None, "q1", "a1")
        conversation_id = self._turn(conversation_id, "q2", "a2")

        history = database.get_history(conversation_id, self.project_id, 3)

        self.assertEqual(
            history, [{"role": "assistant", "content": "a1"}, {"role": "user", "content": "q2"}, {"role": "assistant", "content": "a2"}]
        )

    def test_a_reply_still_streaming_is_left_out(self):
        conversation_id, _reply_id = chat_service.begin_turn(self.project_id, None, "q1")

        self.assertEqual(database.get_history(conversation_id, self.project_id, 6), [{"role": "user", "content": "q1"}])

    def test_another_projects_chat_is_never_read(self):
        conversation_id = self._turn(None, "secret question", "secret answer")
        other = database.create_project("B")["id"]

        self.assertEqual(chat_service.history(other, conversation_id), [])

    def test_a_new_chat_has_no_history(self):
        self.assertEqual(chat_service.history(self.project_id, None), [])


class RestartTests(HistoryTestCase):
    def test_after_a_restart_the_model_still_gets_the_earlier_turns(self):
        conversation_id = self._turn(None, "What is the budget?", "It is 48,500 TND.")
        # A restart: a new process opens the same database file and loads the schema again.
        with patch.object(database, "_initialized", False):
            history = chat_service.history(self.project_id, conversation_id)
        sent = {}

        def post(url, json=None, **_kwargs):
            sent["messages"] = json["messages"]
            response = Mock()
            response.json.return_value = {"message": {"content": "On 14 September."}}
            return response

        with patch.object(orchestrator.requests, "post", post):
            orchestrator.ask("And when was it approved?", project_id=self.project_id, history=history)

        roles_and_text = [(m["role"], m["content"]) for m in sent["messages"]]
        self.assertEqual(
            roles_and_text[1:], [("user", "What is the budget?"), ("assistant", "It is 48,500 TND."), ("user", "And when was it approved?")]
        )


if __name__ == "__main__":
    unittest.main()
