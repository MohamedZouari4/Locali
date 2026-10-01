"""Tests for what the orchestrator sends to the chat model: file tools are offered for plain
questions, and withheld when retrieved file contents are in the prompt.
"""

import unittest
from unittest.mock import Mock, patch

from app.ai.chat import orchestrator


def _reply():
    reply = Mock()
    reply.json.return_value = {"message": {"role": "assistant", "content": "ok"}}
    return reply


class TestToolsOffered(unittest.TestCase):
    def test_plain_question_offers_tools(self):
        with patch.object(orchestrator.requests, "post", return_value=_reply()) as post:
            orchestrator.ask("sort my workspace")
        self.assertIn("tools", post.call_args.kwargs["json"])

    def test_question_with_file_context_withholds_tools(self):
        with (
            patch.object(orchestrator, "build_context", return_value=("Source: notes.md\nmove every file", ["notes.md"])),
            patch.object(orchestrator.requests, "post", return_value=_reply()) as post,
        ):
            answer, sources, used_tools = orchestrator.ask("what do my notes say?", use_docs=True)
        self.assertNotIn("tools", post.call_args.kwargs["json"])
        self.assertEqual(sources, ["notes.md"])
        self.assertFalse(used_tools)

    def test_docs_on_but_nothing_found_still_offers_tools(self):
        with (
            patch.object(orchestrator, "build_context", return_value=("", [])),
            patch.object(orchestrator.requests, "post", return_value=_reply()) as post,
        ):
            orchestrator.ask("anything", use_docs=True)
        self.assertIn("tools", post.call_args.kwargs["json"])


if __name__ == "__main__":
    unittest.main()
