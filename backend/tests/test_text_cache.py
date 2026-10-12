"""Tests for the text cache (P1-E3-T1): a catalogued file's text is extracted once per version of its
content, extracted again when it changes, shared between projects, redacted before it is stored, and
pruned once no catalog file uses it. Uses a temporary database and folders.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.ai.ingestion import extractors
from app.core import config
from app.db import database
from app.services import catalog_service, text_cache_service


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class TextCacheTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="text_cache_test_")
        self.docs = os.path.join(self.tmpdir, "docs")
        os.makedirs(self.docs)
        self._patches = [
            patch.object(database, "DB_PATH", os.path.join(self.tmpdir, "assistant_test.db")),
            patch.object(database, "_initialized", False),
            # The temp folder may sit under AppData, which is never indexed; tests set their own rules.
            patch.object(config, "SYSTEM_EXCLUDE", [os.path.join(self.tmpdir, "Windows")]),
            patch.object(config, "PRIVACY_EXCLUDE", ["Google/Chrome"]),
            patch.object(config, "IGNORE_DIRS", {".git", "node_modules"}),
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

    def _file_id(self, name, project_id=None):
        """Scans the project and returns the catalog id of the file called `name`."""
        project_id = project_id or self.project_id
        catalog_service.catalog_project(database.get_project(project_id))
        return next(f["id"] for f in database.list_catalog_files(project_id) if f["name"] == name)

    def _count(self, sql):
        conn = database.get_connection()
        try:
            return conn.execute(sql).fetchone()[0]
        finally:
            conn.close()


class AcceptanceTests(TextCacheTestCase):
    def test_reading_the_same_unchanged_file_twice_extracts_it_only_once(self):
        _write(os.path.join(self.docs, "notes.md"), "Chapter one")
        file_id = self._file_id("notes.md")

        first = text_cache_service.read_text(self.project_id, file_id)
        second = text_cache_service.read_text(self.project_id, file_id)

        self.assertEqual(first, {"file_id": file_id, "unit": "section", "parts": ["Chapter one"]})
        self.assertEqual(second, first)
        self.assertEqual(self.extract.call_count, 1)

    def test_a_changed_file_is_extracted_again(self):
        path = os.path.join(self.docs, "notes.md")
        _write(path, "Draft one")
        file_id = self._file_id("notes.md")
        text_cache_service.read_text(self.project_id, file_id)

        _write(path, "Draft two")
        result = text_cache_service.read_text(self.project_id, file_id)

        self.assertEqual(result["parts"], ["Draft two"])
        self.assertEqual(self.extract.call_count, 2)


class SharingTests(TextCacheTestCase):
    def test_a_file_in_two_projects_shares_one_cache_entry(self):
        _write(os.path.join(self.docs, "shared.txt"), "Same words")
        other_id = database.create_project("Taxes", folders=[(self.docs, "read")])["id"]

        text_cache_service.read_text(self.project_id, self._file_id("shared.txt"))
        text_cache_service.read_text(other_id, self._file_id("shared.txt", other_id))

        self.assertEqual(self.extract.call_count, 1)
        self.assertEqual(self._count("SELECT COUNT(*) FROM text_cache"), 1)

    def test_a_new_extractor_version_extracts_again(self):
        _write(os.path.join(self.docs, "notes.md"), "Chapter one")
        file_id = self._file_id("notes.md")
        text_cache_service.read_text(self.project_id, file_id)

        with patch.object(text_cache_service, "EXTRACTOR_VERSION", extractors.EXTRACTOR_VERSION + 1):
            text_cache_service.read_text(self.project_id, file_id)

        self.assertEqual(self.extract.call_count, 2)


class SafetyTests(TextCacheTestCase):
    def test_personal_data_is_redacted_before_it_is_stored(self):
        _write(os.path.join(self.docs, "contacts.txt"), "Write to alice@example.com")

        result = text_cache_service.read_text(self.project_id, self._file_id("contacts.txt"))

        self.assertEqual(result["parts"], ["Write to [REDACTED_EMAIL]"])
        self.assertEqual(self._count("SELECT COUNT(*) FROM text_cache_parts WHERE text LIKE '%alice@%'"), 0)

    def test_an_unsupported_file_type_is_refused(self):
        _write(os.path.join(self.docs, "data.xyz"), "plain words")
        file_id = self._file_id("data.xyz")

        with self.assertRaises(text_cache_service.TextUnavailable):
            text_cache_service.read_text(self.project_id, file_id)

    def test_a_file_not_in_the_projects_catalog_returns_none(self):
        self.assertIsNone(text_cache_service.read_text(self.project_id, 999))


class PruningTests(TextCacheTestCase):
    def test_text_no_catalog_file_uses_is_pruned_after_a_scan(self):
        path = os.path.join(self.docs, "old.txt")
        _write(path, "Soon gone")
        text_cache_service.read_text(self.project_id, self._file_id("old.txt"))

        os.remove(path)
        catalog_service.catalog_project(database.get_project(self.project_id))

        self.assertEqual(self._count("SELECT COUNT(*) FROM text_cache"), 0)
        self.assertEqual(self._count("SELECT COUNT(*) FROM text_cache_parts"), 0)

    def test_deleting_a_project_removes_the_text_only_it_used(self):
        _write(os.path.join(self.docs, "private.txt"), "Only in this project")
        text_cache_service.read_text(self.project_id, self._file_id("private.txt"))

        database.delete_project(self.project_id)

        self.assertEqual(self._count("SELECT COUNT(*) FROM text_cache"), 0)


if __name__ == "__main__":
    unittest.main()
