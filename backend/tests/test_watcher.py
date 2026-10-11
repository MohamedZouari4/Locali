"""Tests for the file watcher (P1-E2-T2): changes in project folders update the catalog within seconds,
deleted files leave the index (and so the answers) at once, changed files are queued for re-indexing,
and ignored or sensitive paths are never handled. Uses a temporary database, folders and index; the
acceptance tests run the real watcher thread on real file events.
"""

import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from app.ai.ingestion import pipeline, store
from app.ai.retrieval import sparse_retriever
from app.core import config
from app.db import database
from app.services import catalog_service, rag_service, watch_service


def _write(path, text="hello"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _wait_for(condition, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return False


class WatcherTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="watcher_test_")
        self.docs = os.path.join(self.tmpdir, "docs")
        os.makedirs(self.docs)
        self.vector_dir = os.path.join(self.tmpdir, "vector_store")
        self._patches = [
            patch.object(database, "DB_PATH", os.path.join(self.tmpdir, "assistant_test.db")),
            patch.object(database, "_initialized", False),
            patch.object(config, "VECTOR_DIR", self.vector_dir),
            patch.object(config, "SCAN_DRIVES", []),
            # The temp folder may sit under AppData, which is never indexed; tests set their own rules.
            patch.object(config, "SYSTEM_EXCLUDE", [os.path.join(self.tmpdir, "Windows")]),
            patch.object(config, "PRIVACY_EXCLUDE", ["Google/Chrome"]),
            patch.object(config, "IGNORE_DIRS", {".git", "node_modules"}),
            patch.object(config, "SENSITIVE_FILES", {".claude.json"}),
            patch.object(config, "WATCH_DEBOUNCE_MS", 200),
            patch.object(config, "WATCH_FOLDERS_CHECK_SECONDS", 0.5),
        ]
        for p in self._patches:
            p.start()
        store.close_collection()
        sparse_retriever.invalidate_caches()
        self.project_id = database.create_project("Thesis", folders=[(self.docs, "read")])["id"]

    def tearDown(self):
        watch_service.stop()
        for p in self._patches:
            p.stop()
        store.close_collection()
        sparse_retriever.invalidate_caches()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _catalog(self):
        """{path relative to docs: record id}"""
        files = database.list_catalog_files(self.project_id, limit=10000)
        return {os.path.relpath(f["path"], self.docs).replace(os.sep, "/"): f["id"] for f in files}

    def _index(self, path):
        # A chunk for `path`, as ingestion would store it; embeddings are given, so no Ollama is needed.
        store.get_collection().add(
            ids=[path], documents=[f"text of {path}"], embeddings=[[0.1, 0.2]], metadatas=[{"source": path, "file_hash": "old"}]
        )
        sparse_retriever.invalidate_caches()

    def _start_watcher(self):
        watch_service.start()
        time.sleep(1)  # let the watcher subscribe before the test changes files


class AcceptanceTests(WatcherTestCase):
    def test_a_new_file_appears_in_the_catalog_within_seconds(self):
        self._start_watcher()

        _write(os.path.join(self.docs, "new.txt"))

        self.assertTrue(_wait_for(lambda: "new.txt" in self._catalog(), seconds=5), self._catalog())

    def test_a_deleted_file_disappears_from_answers(self):
        database.add_indexed_folder(self.docs)
        path = os.path.abspath(os.path.join(self.docs, "notes.md"))
        _write(path)
        self._index(path)
        self.assertIn(path, sparse_retriever.all_sources())
        self._start_watcher()

        os.remove(path)

        self.assertTrue(_wait_for(lambda: path not in sparse_retriever.all_sources(), seconds=5))
        self.assertEqual(store.stored_hash(path), None)


class CatalogChangeTests(WatcherTestCase):
    def test_a_rename_in_one_batch_keeps_the_identity(self):
        _write(os.path.join(self.docs, "draft.txt"))
        catalog_service.catalog_project(database.get_project(self.project_id))
        file_id = self._catalog()["draft.txt"]

        old, new = os.path.join(self.docs, "draft.txt"), os.path.join(self.docs, "final.txt")
        os.rename(old, new)
        watch_service.handle_changes([old, new])

        self.assertEqual(self._catalog(), {"final.txt": file_id})

    def test_a_deleted_folder_removes_its_files_and_a_moved_one_keeps_them(self):
        _write(os.path.join(self.docs, "a", "one.txt"))
        _write(os.path.join(self.docs, "b", "two.txt"))
        catalog_service.catalog_project(database.get_project(self.project_id))
        two_id = self._catalog()["b/two.txt"]

        shutil.rmtree(os.path.join(self.docs, "a"))
        os.rename(os.path.join(self.docs, "b"), os.path.join(self.docs, "c"))
        watch_service.handle_changes([os.path.join(self.docs, name) for name in ("a", "b", "c")])

        self.assertEqual(self._catalog(), {"c/two.txt": two_id})

    def test_changes_elsewhere_leave_the_catalog_alone(self):
        _write(os.path.join(self.docs, "kept.txt"))
        catalog_service.catalog_project(database.get_project(self.project_id))
        before = self._catalog()

        watch_service.handle_changes([os.path.join(self.tmpdir, "other", "file.txt")])

        self.assertEqual(self._catalog(), before)

    def test_ignored_folders_and_sensitive_files_are_filtered_out(self):
        self.assertTrue(watch_service.keep_change(None, os.path.join(self.docs, "notes.txt")))
        self.assertFalse(watch_service.keep_change(None, os.path.join(self.docs, ".git", "index")))
        self.assertFalse(watch_service.keep_change(None, os.path.join(self.docs, "app", "node_modules", "x.js")))
        self.assertFalse(watch_service.keep_change(None, os.path.join(self.docs, ".claude.json")))

    def test_project_and_indexed_folders_are_watched_once(self):
        database.add_indexed_folder(self.docs)
        inner = os.path.join(self.docs, "inner")
        os.makedirs(inner)
        database.create_project("Inner", folders=[(inner, "read")])

        self.assertEqual(watch_service.watched_folders(), [self.docs])


class IndexChangeTests(WatcherTestCase):
    def setUp(self):
        super().setUp()
        database.add_indexed_folder(self.docs)

    def test_a_new_or_changed_file_is_queued_for_reindexing(self):
        path = os.path.join(self.docs, "notes.md")
        _write(path)

        watch_service.handle_changes([path])

        jobs = database.list_jobs(kind=rag_service.REINDEX_KIND)
        self.assertEqual([job["params"]["paths"] for job in jobs], [[path]])

    def test_a_deleted_folder_removes_every_indexed_file_under_it(self):
        folder = os.path.join(self.docs, "old")
        paths = [os.path.abspath(os.path.join(folder, name)) for name in ("a.md", "b.md")]
        for path in paths:
            _write(path)
            self._index(path)
        kept = os.path.abspath(os.path.join(self.docs, "kept.md"))
        _write(kept)
        self._index(kept)

        shutil.rmtree(folder)
        watch_service.handle_changes([folder])

        self.assertEqual(set(sparse_retriever.all_sources()), {kept})

    def test_reindexing_drops_the_old_text_of_a_file_that_can_no_longer_be_indexed(self):
        path = os.path.abspath(os.path.join(self.docs, "notes.md"))
        _write(path, "")  # empty now, so it can't be indexed
        self._index(path)

        counts = pipeline.index_paths([path])

        self.assertEqual(counts["removed"], 1)
        self.assertIsNone(store.stored_hash(path))

    def test_reindexing_skips_sensitive_files(self):
        path = os.path.join(self.docs, ".claude.json")
        _write(path, '{"token": "secret"}')

        with patch.object(pipeline, "index_file") as index_file:
            pipeline.index_paths([path])

        index_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
