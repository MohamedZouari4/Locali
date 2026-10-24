"""Tests for tool cards and the tool registry (P1-E4-T1): only tools with a valid card load, so removing a
card makes its tool unavailable; each card declares an output shape the tool keeps to; every tool error
comes back with one of the fixed codes; and at most MAX_TOOLS_PER_STEP tools are offered, lowest risk first.
Runs against a temporary workspace, database and action log.
"""

import dataclasses
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.core.config import MAX_TOOLS_PER_STEP
from app.db import database
from app.services import tool_service
from app.tools import audit_log, file_tools, registry
from app.tools.cards import CARDS, ToolCard
from app.tools.errors import ERROR_CODES, ToolError

ALL_TOOLS = {card.name for card in CARDS}


def _card(name, risk, **changes):
    """A valid card for a one-parameter test tool at the given risk level."""
    card = ToolCard(
        name=name,
        purpose=f"Test tool {name}.",
        parameters={"path": {"type": "string"}},
        output={"type": "string"},
        risk=risk,
        space="workspace",
        access="read" if risk == "L0" else "act",
        undo=None if risk == "L0" else "Put it back.",
    )
    return dataclasses.replace(card, **changes)


def _echo(path):
    return path


class RegistryTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = os.path.realpath(tempfile.mkdtemp(prefix="tool_registry_test_"))
        self.root = os.path.join(self.tmpdir, "workspace")
        os.makedirs(self.root)
        self._patches = [
            patch.object(file_tools, "ALLOWED_ROOT", self.root),
            patch.object(audit_log, "LOG_FILE", os.path.join(self.tmpdir, "logs", "actions.log")),
            patch.object(database, "DB_PATH", os.path.join(self.tmpdir, "assistant_test.db")),
            patch.object(database, "_initialized", False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, name, text=""):
        with open(os.path.join(self.root, name), "w", encoding="utf-8") as f:
            f.write(text)


class LoadingTests(RegistryTestCase):
    def test_every_tool_has_a_valid_card_and_loads(self):
        self.assertEqual(set(registry.TOOLS), set(registry.FUNCTIONS))
        self.assertEqual(set(registry.TOOLS), ALL_TOOLS)

    def test_removing_a_card_makes_its_tool_unavailable(self):
        cards = [card for card in CARDS if card.name != "list_files"]
        with self.assertLogs("app.tools.registry", "WARNING") as logs:
            tools = registry.load(cards, registry.FUNCTIONS)

        with patch.object(registry, "TOOLS", tools):
            offered = {card.name for card in registry.offer(MAX_TOOLS_PER_STEP)}
            result = registry.run("list_files", {"path": "."}, {"list_files"})

        self.assertNotIn("list_files", offered)
        self.assertEqual(result["error"]["code"], "not_available")
        self.assertIn("list_files: it has no card", logs.output[0])

    def test_an_invalid_card_is_refused(self):
        broken = [
            _card("echo", "L9"),
            _card("echo", "L0", space="internet"),
            _card("echo", "L0", undo="Nothing to undo."),
            _card("echo", "L2", undo=None),
            _card("echo", "L1", access="read"),
            _card("echo", "L0", output={}),
            _card("echo", "L0", required=("folder",)),
            _card("echo", "L0", parameters={"folder": {"type": "string"}}),
        ]
        for card in broken:
            with self.subTest(card=card), self.assertLogs("app.tools.registry", "WARNING"):
                self.assertEqual(registry.load([card], {"echo": _echo}), {})

    def test_a_card_for_a_missing_tool_is_a_mistake(self):
        with self.assertRaises(ValueError):
            registry.load([_card("ghost", "L0")], {})


class OutputTests(RegistryTestCase):
    def test_each_tool_returns_its_declared_output_shape(self):
        self._write("empty.txt")
        self._write("full.txt", "text")
        project_id = database.create_project("Project", folders=[(self.root, "read")])["id"]
        calls = [
            ("list_files", {"path": "."}),
            ("find_empty_files", {"folder": "."}),
            ("create_folder", {"path": "reports"}),
            ("move_file", {"src": "full.txt", "dst": "reports/full.txt"}),
            ("organize_by_extension", {"folder": "reports"}),
            ("project_overview", {"project_id": project_id}),
        ]
        self.assertEqual({name for name, _ in calls}, ALL_TOOLS)
        python_types = {"array": list, "string": str, "object": dict}
        for name, arguments in calls:
            with self.subTest(name):
                card, _ = registry.TOOLS[name]
                result = registry.run(name, arguments, ALL_TOOLS)
                self.assertTrue(result["ok"], result)
                self.assertIsInstance(result["result"], python_types[card.output["type"]])
                if card.output["type"] == "array":
                    self.assertTrue(all(isinstance(item, str) for item in result["result"]))

    def test_project_overview_is_read_only_and_returns_an_object(self):
        project_id = database.create_project("Project", folders=[(self.root, "read")])["id"]

        result = registry.run("project_overview", {"project_id": project_id}, ALL_TOOLS)

        self.assertTrue(result["ok"], result)
        self.assertIsInstance(result["result"], dict)


class ErrorCodeTests(RegistryTestCase):
    def test_every_tool_error_returns_one_of_the_fixed_codes(self):
        self._write("a.txt")
        cases = [
            ("outside_boundary", "list_files", {"path": "../.."}),
            ("outside_boundary", "move_file", {"src": "a.txt", "dst": "../escaped.txt"}),
            ("not_found", "list_files", {"path": "missing"}),
            ("not_found", "move_file", {"src": "missing.txt", "dst": "b.txt"}),
            ("not_a_folder", "list_files", {"path": "a.txt"}),
            ("not_a_folder", "organize_by_extension", {"folder": "a.txt"}),
            ("invalid_arguments", "move_file", {"src": "a.txt"}),
            ("invalid_arguments", "list_files", {"path": ".", "recursive": True}),
            ("invalid_arguments", "list_files", "not an object"),
            ("not_available", "delete_everything", {}),
        ]
        for code, name, arguments in cases:
            with self.subTest(code=code, tool=name):
                result = registry.run(name, arguments, ALL_TOOLS | {"delete_everything"})
                self.assertFalse(result["ok"])
                self.assertIn(result["error"]["code"], ERROR_CODES)
                self.assertEqual(result["error"]["code"], code)
                self.assertTrue(result["error"]["message"])

    def test_a_tool_not_offered_this_step_cannot_run(self):
        result = registry.run("create_folder", {"path": "reports"}, {"list_files"})

        self.assertEqual(result["error"]["code"], "not_available")
        self.assertFalse(os.path.exists(os.path.join(self.root, "reports")))

    def test_an_unexpected_failure_is_reported_plainly(self):
        def broken(path):
            raise RuntimeError("internal detail C:\\secret\\path")

        tools = registry.load([_card("broken", "L0")], {"broken": broken})
        with patch.object(registry, "TOOLS", tools), self.assertLogs("app.tools.registry", "ERROR"):
            result = registry.run("broken", {"path": "."}, {"broken"})

        self.assertEqual(result["error"], {"code": "failed", "message": ERROR_CODES["failed"]})

    def test_a_blocked_call_is_audited(self):
        registry.run("list_files", {"path": "../.."}, ALL_TOOLS)

        valid, problem = audit_log.verify_log_integrity()
        self.assertTrue(valid, problem)
        with open(audit_log.LOG_FILE, encoding="utf-8") as f:
            self.assertIn("blocked list_files", f.read())

    def test_a_tool_error_needs_a_known_code(self):
        self.assertEqual(ToolError("too_large").message, ERROR_CODES["too_large"])
        with self.assertRaises(ValueError):
            ToolError("exploded")

    def test_the_file_routes_report_the_same_codes(self):
        with self.assertRaises(tool_service.ToolServiceError) as blocked:
            tool_service.list_files("../..")
        with self.assertRaises(tool_service.ToolServiceError) as missing:
            tool_service.list_files("missing")

        self.assertEqual((blocked.exception.code, blocked.exception.status_code), ("outside_boundary", 403))
        self.assertEqual((missing.exception.code, missing.exception.status_code), ("not_found", 404))


class OfferTests(RegistryTestCase):
    def test_at_most_n_tools_are_offered_lowest_risk_first(self):
        risks = ["L4", "L3", "L2", "L1", "L0", "L0", "L1", "L2"]
        cards = [_card(f"tool{n}", risk) for n, risk in enumerate(risks)]
        tools = registry.load(cards, {card.name: _echo for card in cards})

        with patch.object(registry, "TOOLS", tools):
            offered = registry.offer(6)

        self.assertEqual([card.risk for card in offered], ["L0", "L0", "L1", "L1", "L2", "L2"])
        self.assertEqual([card.name for card in offered][:2], ["tool4", "tool5"])

    def test_today_every_tool_fits_in_one_step(self):
        self.assertLessEqual(len(registry.TOOLS), MAX_TOOLS_PER_STEP)
        self.assertEqual({card.name for card in registry.offer(MAX_TOOLS_PER_STEP)}, ALL_TOOLS)


if __name__ == "__main__":
    unittest.main()
