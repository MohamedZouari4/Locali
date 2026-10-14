"""Tests for idle-time pre-extraction (P1-E3-T5): while the computer is idle on mains power and Locali has
nothing else to do, small files are read into the text cache ahead of time; it never starts, and stops
before the next file, when the user comes back, the computer goes on battery, a job is queued or a chat
reply is being written. Idleness and power are faked, so this runs on every OS. Uses a temporary database.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.ai.ingestion import extractors
from app.core import config, system_activity
from app.db import database
from app.services import catalog_service, preextract_service, text_cache_service


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class PreextractTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="preextract_test_")
        self.docs = os.path.join(self.tmpdir, "docs")
        os.makedirs(self.docs)
        self.idle = 600  # seconds since the last input, as system_activity reports it
        self.battery = False
        self._patches = [
            patch.object(database, "DB_PATH", os.path.join(self.tmpdir, "assistant_test.db")),
            patch.object(database, "_initialized", False),
            # The temp folder may sit under AppData, which is never indexed; tests set their own rules.
            patch.object(config, "SYSTEM_EXCLUDE", [os.path.join(self.tmpdir, "Windows")]),
            patch.object(config, "PRIVACY_EXCLUDE", ["Google/Chrome"]),
            patch.object(config, "IGNORE_DIRS", {".git", "node_modules"}),
            patch.object(config, "PREEXTRACT_ENABLED", True),
            patch.object(system_activity, "idle_seconds", lambda: self.idle),
            patch.object(system_activity, "on_battery", lambda: self.battery),
            patch.object(preextract_service, "_unreadable", set()),
        ]
        for p in self._patches:
            p.start()
        # Counts real extractions while still running the real readers.
        extract = patch.object(text_cache_service, "extract_parts", wraps=extractors.extract_parts)
        self.extract = extract.start()
        self._patches.append(extract)
        self.project_id = database.create_project("Thesis", folders=[(self.docs, "read")])["id"]

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _scan(self, *names):
        """Writes a small text file for each name and catalogs the project."""
        for name in names:
            _write(os.path.join(self.docs, name), f"Notes in {name}")
        catalog_service.catalog_project(database.get_project(self.project_id))

    def _file_id(self, name):
        return next(f["id"] for f in database.list_catalog_files(self.project_id) if f["name"] == name)

    def _waiting(self):
        return len(preextract_service.files_to_read())


class ReadAheadTests(PreextractTestCase):
    def test_idle_time_reads_small_files_so_the_first_question_does_not_extract(self):
        self._scan("a.md", "b.txt")

        result = preextract_service.read_ahead()

        self.assertEqual(result, {"read": 2, "unreadable": 0, "stopped": "done"})
        self.extract.reset_mock()
        text_cache_service.read_text(self.project_id, self._file_id("a.md"))
        self.extract.assert_not_called()

    def test_large_files_and_images_are_left_for_a_real_read(self):
        self._scan("small.txt")
        _write(os.path.join(self.docs, "big.txt"), "x" * (config.PREEXTRACT_MAX_FILE_MB * 1024 * 1024 + 1))
        _write(os.path.join(self.docs, "scan.png"), "not really a picture")
        catalog_service.catalog_project(database.get_project(self.project_id))

        self.assertEqual(preextract_service.read_ahead()["read"], 1)
        self.assertEqual(self._waiting(), 0)

    def test_a_file_that_cant_be_read_is_not_tried_again(self):
        self._scan("fake.pdf")  # text, not a PDF, so it is refused

        self.assertEqual(preextract_service.read_ahead()["unreadable"], 1)
        self.assertEqual(self._waiting(), 0)

    def test_files_cached_by_older_readers_are_read_again(self):
        self._scan("a.md")
        preextract_service.read_ahead()

        with patch.object(preextract_service, "EXTRACTOR_VERSION", extractors.EXTRACTOR_VERSION + 1):
            self.assertEqual(self._waiting(), 1)


class NeverSlowsActiveUseTests(PreextractTestCase):
    """The acceptance criterion: pre-extraction never slows down active use."""

    def test_nothing_is_read_while_the_user_is_active(self):
        self._scan("a.md")
        self.idle = 5

        self.assertEqual(preextract_service.read_ahead(), {"read": 0, "unreadable": 0, "stopped": "user_active"})
        self.assertIsNone(preextract_service.queue_if_idle())

    def test_nothing_is_read_on_battery(self):
        self._scan("a.md")
        self.battery = True

        self.assertEqual(preextract_service.read_ahead()["stopped"], "battery")
        self.assertIsNone(preextract_service.queue_if_idle())

    def test_nothing_is_read_where_idleness_or_power_cant_be_measured(self):
        self._scan("a.md")
        self.idle = None

        self.assertEqual(preextract_service.read_ahead()["stopped"], "unsupported")

    def test_nothing_is_read_when_turned_off(self):
        self._scan("a.md")

        with patch.object(config, "PREEXTRACT_ENABLED", False):
            self.assertEqual(preextract_service.read_ahead()["stopped"], "disabled")

    def test_a_job_stops_before_the_next_file_when_the_user_comes_back(self):
        self._scan("a.md", "b.md", "c.md")
        real_read = text_cache_service.read_text

        def read_then_user_returns(*args):
            self.idle = 0
            return real_read(*args)

        with patch.object(text_cache_service, "read_text", read_then_user_returns):
            result = preextract_service.read_ahead()

        self.assertEqual(result, {"read": 1, "unreadable": 0, "stopped": "user_active"})

    def test_a_job_gives_way_to_a_job_the_user_starts(self):
        self._scan("a.md", "b.md", "c.md")
        real_read = text_cache_service.read_text

        def read_then_queue_a_scan(*args):
            catalog_service.start_scan(self.project_id)
            return real_read(*args)

        with patch.object(text_cache_service, "read_text", read_then_queue_a_scan):
            result = preextract_service.read_ahead()

        self.assertEqual(result["read"], 1)
        self.assertEqual(result["stopped"], "busy")

    def test_nothing_is_read_while_a_chat_reply_is_being_written(self):
        self._scan("a.md")
        database.begin_turn(None, "What is in my notes?", self.project_id)

        self.assertEqual(preextract_service.read_ahead()["stopped"], "busy")
        self.assertIsNone(preextract_service.queue_if_idle())

    def test_a_job_stops_when_its_time_is_up(self):
        self._scan("a.md", "b.md")
        times = iter([0, 0, config.PREEXTRACT_BATCH_SECONDS])

        result = preextract_service.read_ahead(clock=lambda: next(times))

        self.assertEqual(result, {"read": 1, "unreadable": 0, "stopped": "time"})


class SchedulerTests(PreextractTestCase):
    def test_a_job_is_queued_only_when_idle_and_files_are_waiting(self):
        self.assertIsNone(preextract_service.queue_if_idle())  # nothing catalogued yet
        self._scan("a.md")

        job = database.get_job(preextract_service.queue_if_idle())

        self.assertEqual((job["kind"], job["state"]), ("preextract", "queued"))
        self.assertIsNone(preextract_service.queue_if_idle())  # one at a time


if __name__ == "__main__":
    unittest.main()
