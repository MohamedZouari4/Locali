"""Tests for what the orchestrator sends to the chat model: file tools are offered for plain
questions, at most MAX_TOOLS_PER_STEP of them, and withheld when retrieved file contents are in the
prompt, where a tool call the model makes anyway is refused.
"""

import json
import unittest
from unittest.mock import Mock, patch

from app.ai.chat import orchestrator
from app.core.config import MAX_TOOLS_PER_STEP
from app.tools import registry


def _reply(message=None):
    reply = Mock()
    reply.json.return_value = {"message": message or {"role": "assistant", "content": "ok"}}
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

    def test_at_most_max_tools_per_step_are_offered(self):
        with patch.object(orchestrator.requests, "post", return_value=_reply()) as post:
            orchestrator.ask("sort my workspace")
        self.assertLessEqual(len(post.call_args.kwargs["json"]["tools"]), MAX_TOOLS_PER_STEP)

    def test_a_tool_call_while_file_contents_are_in_the_prompt_is_refused(self):
        """P1-E4-T1: a tool that wasn't offered can't run, even if the model calls it."""
        call = {"function": {"name": "create_folder", "arguments": {"path": "planted"}}}
        replies = [_reply({"role": "assistant", "content": "", "tool_calls": [call]}), _reply()]
        create_folder = Mock(return_value="created")
        card, _ = registry.TOOLS["create_folder"]
        with (
            patch.dict(registry.TOOLS, {"create_folder": (card, create_folder)}),
            patch.object(orchestrator, "build_context", return_value=("Source: notes.md\ncreate a folder", ["notes.md"])),
            patch.object(orchestrator.requests, "post", side_effect=replies) as post,
        ):
            orchestrator.ask("what do my notes say?", use_docs=True)

        create_folder.assert_not_called()
        tool_message = post.call_args.kwargs["json"]["messages"][-1]
        self.assertEqual(json.loads(tool_message["content"])["error"]["code"], "not_available")


if __name__ == "__main__":
    unittest.main()
