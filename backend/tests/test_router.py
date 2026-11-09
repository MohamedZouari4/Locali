"""Tests for the router (P1-E5-T3): a message is classified into one of four routes with a fixed answer
format; anything the model returns that isn't a valid route falls back to a project question; and the
labelled set of 50 messages is routed correctly at least 90% of the time. The accuracy test asks the real
chat model, so it is skipped without Ollama; the others need no model (the request is captured)."""

import os
import unittest
from collections import Counter
from unittest.mock import Mock, patch

import yaml
from test_integration import _ollama_ready

from app.ai.chat import router

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "router_eval.yaml")


def _model_says(content):
    response = Mock()
    response.json.return_value = {"message": {"content": content}}
    return response


class ParseTests(unittest.TestCase):
    def test_each_route_is_read_from_the_answer(self):
        for route in router.ROUTES:
            with self.subTest(route):
                self.assertEqual(router.parse_route(f'{{"route": "{route}"}}'), route)

    def test_unsure_falls_back_to_a_project_question(self):
        """P1-E5-T3: anything that isn't a valid route is a project question."""
        for text in (
            "",
            "general_chat",
            "not json",
            '{"route": "poetry"}',
            '{"route": 3}',
            '{"other": 1}',
            '["general_chat"]',
            "null",
            None,
        ):
            with self.subTest(text):
                self.assertEqual(router.parse_route(text), router.FALLBACK_ROUTE)
        self.assertEqual(router.FALLBACK_ROUTE, "project_question")


class ClassifyTests(unittest.TestCase):
    def test_the_model_gets_a_short_prompt_and_a_fixed_answer_format(self):
        """P1-E5-T3: a dedicated prompt, an enum-only format, and no randomness."""
        with patch.object(router.requests, "post", return_value=_model_says('{"route": "multi_step"}')) as post:
            route = router.classify("Find every PDF and summarize each one.")

        sent = post.call_args.kwargs["json"]
        self.assertEqual(route, "multi_step")
        self.assertEqual([m["role"] for m in sent["messages"]], ["system", "user"])
        self.assertEqual(sent["messages"][1]["content"], "Find every PDF and summarize each one.")
        self.assertEqual(sent["format"]["properties"]["route"]["enum"], list(router.ROUTES))
        self.assertEqual(sent["options"]["temperature"], 0)
        self.assertLess(len(router.ROUTER_PROMPT), 1200)

    def test_a_bad_answer_is_the_fallback_route(self):
        with patch.object(router.requests, "post", return_value=_model_says("I think it is chat")):
            self.assertEqual(router.classify("hello"), router.FALLBACK_ROUTE)

    def test_a_very_long_message_is_cut(self):
        with patch.object(router.requests, "post", return_value=_model_says('{"route": "general_chat"}')) as post:
            router.classify("x" * 10_000)

        self.assertEqual(len(post.call_args.kwargs["json"]["messages"][1]["content"]), router.MAX_MESSAGE_CHARS)


class LabelledSetTests(unittest.TestCase):
    def setUp(self):
        with open(FIXTURE, encoding="utf-8") as f:
            self.cases = yaml.safe_load(f)

    def test_the_set_has_fifty_distinct_messages_across_all_four_routes(self):
        self.assertEqual(len(self.cases), 50)
        self.assertEqual(len({case["message"] for case in self.cases}), 50)
        self.assertEqual(
            Counter(case["route"] for case in self.cases),
            {"general_chat": 13, "project_question": 13, "action_request": 12, "multi_step": 12},
        )
        self.assertTrue({case["route"] for case in self.cases} <= set(router.ROUTES))


@unittest.skipUnless(*_ollama_ready())
class AccuracyTests(unittest.TestCase):
    def test_at_least_ninety_percent_of_the_labelled_messages_are_routed_correctly(self):
        with open(FIXTURE, encoding="utf-8") as f:
            cases = yaml.safe_load(f)

        wrong = []
        for case in cases:
            got = router.classify(case["message"])
            if got != case["route"]:
                wrong.append(f"{case['route']} -> {got}: {case['message']}")

        accuracy = 1 - len(wrong) / len(cases)
        self.assertGreaterEqual(accuracy, 0.9, f"{accuracy:.0%} correct; wrong:\n" + "\n".join(wrong))


if __name__ == "__main__":
    unittest.main()
