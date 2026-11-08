"""Tests for the find files tool (P1-E4-T3): 'PDFs changed this month' returns the right files; names match
by pattern or by part, in any script; size and period filters work; at most MAX_FOUND_FILES come back with
the total; it reads the catalog, not the disk; and it only searches the chat's own project. Uses a temporary
database and folders. The last test asks the real chat model, so it is skipped without Ollama.
"""

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from test_integration import _ollama_ready

from app.ai.chat import orchestrator
from app.core import config
from app.db import database
from app.services import catalog_service
from app.tools import registry


def _write(path, modified, size=10):
    """A file of `size` bytes last modified at `modified` (naive local time)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)
    stamp = modified.timestamp()
    os.utime(path, (stamp, stamp))


def _month_start():
    now = datetime.now()
    return datetime(now.year, now.month, 1)


def _this_month():
    # Halfway between the start of this month and now, so it is this month whatever day the tests run.
    start = _month_start()
    return start + (datetime.now() - start) / 2


def _last_month():
    return _month_start() - timedelta(days=2)


class FindFilesTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = os.path.realpath(tempfile.mkdtemp(prefix="find_files_test_"))
        self.docs = os.path.join(self.tmpdir, "Thesis")
        os.makedirs(self.docs)
        self._patches = [
            patch.object(database, "DB_PATH", os.path.join(self.tmpdir, "assistant_test.db")),
            patch.object(database, "_initialized", False),
            # The temp folder may sit under AppData, which is never catalogued; tests set their own rules.
            patch.object(config, "SYSTEM_EXCLUDE", [os.path.join(self.tmpdir, "Windows")]),
            patch.object(config, "PRIVACY_EXCLUDE", ["Google/Chrome"]),
            patch.object(config, "IGNORE_DIRS", {".git", "node_modules"}),
        ]
        for p in self._patches:
            p.start()
        self.project_id = database.create_project("Thesis", folders=[(self.docs, "read")])["id"]

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _scan(self, project_id=None):
        catalog_service.catalog_project(database.get_project(project_id or self.project_id))

    def _find(self, project_id=None, **arguments):
        """The tool's result through the registry, as the chat model gets it."""
        return registry.run("find_files", arguments, {"find_files"}, project_id or self.project_id)

    def _names(self, **arguments):
        result = self._find(**arguments)
        self.assertTrue(result["ok"], result)
        return sorted(os.path.basename(file["path"]) for file in result["result"]["files"])


class AcceptanceTests(FindFilesTestCase):
    def test_pdfs_changed_this_month_are_found(self):
        _write(os.path.join(self.docs, "report.pdf"), _this_month())
        _write(os.path.join(self.docs, "chapters", "Plan.PDF"), _this_month())
        _write(os.path.join(self.docs, "old.pdf"), _last_month())
        _write(os.path.join(self.docs, "notes.docx"), _this_month())
        self._scan()

        self.assertEqual(self._names(extension="pdf", changed="this_month"), ["Plan.PDF", "report.pdf"])


class FilterTests(FindFilesTestCase):
    def test_names_match_by_pattern_or_part_ignoring_case_in_any_script(self):
        for name in ("Report-2026.pdf", "final report.docx", "تقرير.pdf", "summary.txt"):
            _write(os.path.join(self.docs, name), _this_month())
        self._scan()

        self.assertEqual(self._names(name="report"), ["Report-2026.pdf", "final report.docx"])
        self.assertEqual(self._names(name="report*"), ["Report-2026.pdf"])
        self.assertEqual(self._names(name="تقرير"), ["تقرير.pdf"])
        self.assertEqual(self._names(extension=".PDF, txt"), ["Report-2026.pdf", "summary.txt", "تقرير.pdf"])

    def test_size_and_period_filters(self):
        _write(os.path.join(self.docs, "big.csv"), _this_month(), size=3 * 1024 * 1024)
        _write(os.path.join(self.docs, "small.csv"), _this_month(), size=100)
        _write(os.path.join(self.docs, "today.csv"), datetime.now() - timedelta(minutes=1))
        _write(os.path.join(self.docs, "last_year.csv"), datetime(datetime.now().year - 1, 6, 1))
        self._scan()

        self.assertEqual(self._names(larger_than_mb=1), ["big.csv"])
        self.assertEqual(self._names(smaller_than_mb="0.5", changed="today"), ["today.csv"])
        self.assertNotIn("last_year.csv", self._names(changed="this_year"))
        self.assertIn("last_year.csv", self._names())

    def test_results_are_capped_with_the_total(self):
        for n in range(catalog_service.MAX_FOUND_FILES + 10):
            _write(os.path.join(self.docs, f"page{n:02d}.txt"), _this_month() - timedelta(minutes=n))
        self._scan()

        result = self._find(extension="txt")["result"]

        self.assertEqual((result["total"], result["shown"]), (catalog_service.MAX_FOUND_FILES + 10, catalog_service.MAX_FOUND_FILES))
        self.assertEqual(os.path.basename(result["files"][0]["path"]), "page00.txt")  # most recently changed first
        self.assertIn("10 more match", result["note"])
        self.assertEqual(set(result["files"][0]), {"id", "path", "size", "modified"})

    def test_it_reads_the_catalog_not_the_disk(self):
        _write(os.path.join(self.docs, "gone.pdf"), _this_month())
        self._scan()
        os.remove(os.path.join(self.docs, "gone.pdf"))
        _write(os.path.join(self.docs, "new.pdf"), _this_month())

        with (
            patch("os.scandir", side_effect=AssertionError("read the disk")),
            patch("os.stat", side_effect=AssertionError("read the disk")),
        ):
            names = self._names(extension="pdf")

        self.assertEqual(names, ["gone.pdf"])


class ArgumentTests(FindFilesTestCase):
    def test_arguments_it_cant_read_are_refused(self):
        for arguments in ({"changed": "last_decade"}, {"larger_than_mb": "big"}, {"smaller_than_mb": -1}, {"extension": 5}):
            with self.subTest(arguments=arguments):
                self.assertEqual(self._find(**arguments)["error"]["code"], "invalid_arguments")


class ScopeTests(FindFilesTestCase):
    def test_only_the_chats_project_is_searched(self):
        other_docs = os.path.join(self.tmpdir, "Taxes")
        _write(os.path.join(other_docs, "return.pdf"), _this_month())
        other_id = database.create_project("Taxes", folders=[(other_docs, "read")])["id"]
        self._scan(other_id)

        self.assertEqual(self._names(extension="pdf"), [])
        self.assertEqual(self._find(project_id=other_id, extension="pdf")["result"]["total"], 1)

    def test_the_model_cant_choose_the_project(self):
        result = registry.run("find_files", {"project_id": "other"}, {"find_files"}, self.project_id)
        self.assertEqual(result["error"]["code"], "invalid_arguments")

        without_project = registry.run("find_files", {}, {"find_files"})
        self.assertEqual(without_project["error"]["code"], "not_available")


@unittest.skipUnless(*_ollama_ready())
class AgentTests(FindFilesTestCase):
    def test_the_agent_finds_pdfs_changed_this_month(self):
        _write(os.path.join(self.docs, "report.pdf"), _this_month())
        _write(os.path.join(self.docs, "old.pdf"), _last_month())
        _write(os.path.join(self.docs, "notes.docx"), _this_month())
        self._scan()

        with patch.object(registry, "run", wraps=registry.run) as run:
            answer, _sources, _used_tools = orchestrator.ask("Find PDFs changed this month", project_id=self.project_id)

        calls = [call.args for call in run.call_args_list if call.args[0] == "find_files"]
        self.assertTrue(calls, "find_files was not called")
        self.assertIn("report.pdf", answer)
        self.assertNotIn("old.pdf", answer)


if __name__ == "__main__":
    unittest.main()
