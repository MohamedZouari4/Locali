"""Tests for indexed folders: which folders are refused and why, the /folders routes, ingestion
walking the chosen folders, and a removed folder's files leaving the index.
Uses a temporary database and folders; Ollama and ChromaDB aren't needed.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.ai.ingestion import pipeline, walker
from app.api.main import app
from app.core import config
from app.core.security import API_TOKEN
from app.db import database
from app.jobs import worker
from app.services import rag_service


class FolderTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="folders_test_")
        self.docs = self._mkdir("docs")
        self._patches = [
            patch.object(database, "DB_PATH", os.path.join(self.tmpdir, "assistant_test.db")),
            patch.object(database, "_initialized", False),
            # The temp folder may sit under AppData, which is never indexed; tests set their own rules.
            patch.object(config, "SYSTEM_EXCLUDE", [os.path.join(self.tmpdir, "Windows")]),
            patch.object(config, "PRIVACY_EXCLUDE", ["Google/Chrome"]),
            patch.object(config, "IGNORE_DIRS", {".git"}),
            patch.object(config, "SCAN_DRIVES", []),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(app, headers={"Authorization": f"Bearer {API_TOKEN}"})

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _mkdir(self, *parts):
        path = os.path.join(self.tmpdir, *parts)
        os.makedirs(path, exist_ok=True)
        return path

    def _add(self, path):
        return self.client.post("/folders", json={"path": path})


class AddFolderTests(FolderTestCase):
    def test_a_folder_is_added_and_listed(self):
        response = self._add(self.docs)

        self.assertEqual(response.status_code, 201)
        self.assertEqual([folder["path"] for folder in self.client.get("/folders").json()], [os.path.normpath(self.docs)])

    def test_refused_folders_say_why(self):
        cases = {
            "docs": "Choose a folder with a full path",
            os.path.join(self.tmpdir, "missing"): "doesn't exist or isn't a folder",
            self._mkdir("Windows", "System32"): "can't be indexed because it is a system folder",
            self._mkdir("Profile", "Google", "Chrome"): "can't be indexed because it holds private app data",
            self._mkdir("project", ".git"): "can't be indexed because it is inside a folder that is never indexed (.git)",
        }
        for path, message in cases.items():
            with self.subTest(path=path):
                response = self._add(path)
                self.assertEqual(response.status_code, 422)
                self.assertIn(message, response.json()["detail"])
        self.assertEqual(self.client.get("/folders").json(), [])

    def test_a_folder_already_covered_is_refused(self):
        self._add(self.docs)

        for path, message in ((self.docs, "is already in the list"), (self._mkdir("docs", "notes"), "is already indexed as part of")):
            with self.subTest(path=path):
                response = self._add(path)
                self.assertEqual(response.status_code, 422)
                self.assertIn(message, response.json()["detail"])

    def test_adding_a_parent_replaces_the_folders_inside_it(self):
        self._add(self.docs)
        self._add(self._mkdir("photos"))

        self._add(self.tmpdir)

        self.assertEqual([folder["path"] for folder in self.client.get("/folders").json()], [os.path.normpath(self.tmpdir)])

    def test_the_routes_require_the_token(self):
        self.assertEqual(TestClient(app).get("/folders").status_code, 401)


class RemoveFolderTests(FolderTestCase):
    def test_removing_a_folder_queues_a_job_to_forget_its_files(self):
        folder_id = self._add(self.docs).json()["id"]

        self.assertEqual(self.client.delete(f"/folders/{folder_id}").status_code, 204)

        self.assertEqual(self.client.get("/folders").json(), [])
        [job] = database.list_jobs(kind=rag_service.FORGET_FOLDER_KIND)
        self.assertEqual(job["params"], {"path": os.path.normpath(self.docs)})

    def test_removing_an_unknown_folder_is_404(self):
        self.assertEqual(self.client.delete("/folders/999").status_code, 404)

    def test_forget_folder_keeps_files_still_under_another_root(self):
        notes = os.path.join(self.docs, "notes.md")
        shared = os.path.join(self.tmpdir, "shared", "plan.md")
        elsewhere = os.path.join(self.tmpdir, "elsewhere", "x.md")
        store = MagicMock()
        store.indexed_sources.return_value = [notes, shared, elsewhere]

        with (
            patch.object(pipeline, "store", store),
            patch.object(pipeline, "scan_roots", return_value=[os.path.join(self.tmpdir, "shared")]),
        ):
            removed = pipeline.forget_folder(self.docs)

        self.assertEqual(removed, 1)
        store.delete_source.assert_called_once_with(notes)

    def test_the_forget_job_runs_and_refreshes_search(self):
        job_id = database.enqueue_job(rag_service.FORGET_FOLDER_KIND, {"path": self.docs})
        with (
            patch.dict(worker.HANDLERS, {rag_service.FORGET_FOLDER_KIND: rag_service.run_forget_folder_job}),
            patch.object(rag_service, "forget_folder", return_value=3) as forget,
            patch.object(rag_service, "invalidate_caches") as invalidate,
        ):
            worker.run_job(database.claim_next_job())

        job = database.get_job(job_id)
        self.assertEqual((job["state"], job["result"]), ("done", {"removed": 3}))
        self.assertEqual(forget.call_args.args, (self.docs,))
        invalidate.assert_called_once()


class ScanRootTests(FolderTestCase):
    def test_scan_roots_are_the_chosen_folders_then_scan_drives_without_duplicates(self):
        self._add(self.docs)
        extra = self._mkdir("extra")

        with patch.object(config, "SCAN_DRIVES", [extra, self.docs]):
            self.assertEqual(walker.scan_roots(), [os.path.normpath(self.docs), extra])

    def test_ingestion_walks_the_chosen_folders(self):
        self._add(self.docs)

        with patch.object(pipeline, "walk_data_dir", return_value=iter([])) as walk:
            pipeline.ingest_all()

        walk.assert_called_once_with([os.path.normpath(self.docs)])

    def test_with_no_folders_nothing_is_ingested_or_pruned(self):
        store = MagicMock()
        with patch.object(pipeline, "store", store):
            self.assertEqual(pipeline.ingest_all()["scanned"], 0)
            self.assertEqual(pipeline.prune_stale(), 0)
        store.delete_source.assert_not_called()

    def test_pruning_drops_files_outside_the_chosen_folders(self):
        self._add(self.docs)
        inside = os.path.join(self.docs, "a.md")
        outside = os.path.join(self.tmpdir, "old", "b.md")
        for path in (inside, outside):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").close()
        store = MagicMock()
        store.indexed_sources.return_value = [inside, outside]

        with patch.object(pipeline, "store", store):
            self.assertEqual(pipeline.prune_stale(), 1)
        store.delete_source.assert_called_once_with(outside)


if __name__ == "__main__":
    unittest.main()
