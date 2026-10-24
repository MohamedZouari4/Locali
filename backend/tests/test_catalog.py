"""Tests for the file catalog (P1-E2-T1): scanning a project's folders as a background job, keeping each
file's identity through renames, moves and safe saves, the ignore rules, links, and the routes.
Uses a temporary database and folders.
"""

import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.main import app
from app.catalog import scanner
from app.core import config
from app.core.security import API_TOKEN
from app.db import database
from app.jobs import worker
from app.services import catalog_service


def _write(path, text="hello"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _link_folder(link, target):
    # A symbolic link, or a junction on Windows without the privilege (as in test_project_boundary.py).
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        import _winapi

        _winapi.CreateJunction(target, link)


class CatalogTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="catalog_test_")
        self.docs = os.path.join(self.tmpdir, "docs")
        os.makedirs(self.docs)
        self._patches = [
            patch.object(database, "DB_PATH", os.path.join(self.tmpdir, "assistant_test.db")),
            patch.object(database, "_initialized", False),
            # The temp folder may sit under AppData, which is never indexed; tests set their own rules.
            patch.object(config, "SYSTEM_EXCLUDE", [os.path.join(self.tmpdir, "Windows")]),
            patch.object(config, "PRIVACY_EXCLUDE", ["Google/Chrome"]),
            patch.object(config, "IGNORE_DIRS", {".git", "node_modules"}),
            patch.object(config, "SENSITIVE_FILES", {".claude.json"}),
        ]
        for p in self._patches:
            p.start()
        self.project_id = database.create_project("Thesis", folders=[(self.docs, "read")])["id"]

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _scan(self, project_id=None):
        return catalog_service.catalog_project(database.get_project(project_id or self.project_id))

    def _catalog(self, project_id=None):
        """{path relative to docs: record id}"""
        files = database.list_catalog_files(project_id or self.project_id, limit=10000)
        return {os.path.relpath(f["path"], self.docs).replace(os.sep, "/"): f["id"] for f in files}


class AcceptanceTests(CatalogTestCase):
    def test_a_2000_file_project_is_catalogued_well_under_a_minute(self):
        for i in range(2000):
            _write(os.path.join(self.docs, f"folder{i % 40}", f"file{i}.txt"))
        job_id = database.enqueue_job(catalog_service.CATALOG_KIND, {"project_id": self.project_id}, self.project_id)

        started = time.perf_counter()
        result = catalog_service.run_catalog_job({"project_id": self.project_id}, worker.JobContext(job_id))
        elapsed = time.perf_counter() - started

        self.assertEqual(result["files"], 2000)
        self.assertEqual(len(self._catalog()), 2000)
        self.assertLess(elapsed, 15)

    def test_renaming_a_file_keeps_its_identity(self):
        _write(os.path.join(self.docs, "draft.txt"))
        self._scan()
        file_id = self._catalog()["draft.txt"]

        os.rename(os.path.join(self.docs, "draft.txt"), os.path.join(self.docs, "final.txt"))
        result = self._scan()

        self.assertEqual(self._catalog(), {"final.txt": file_id})
        self.assertEqual((result["renamed"], result["added"], result["removed"]), (1, 0, 0))

    def test_project_overview_summarizes_catalog_structure_and_types(self):
        _write(os.path.join(self.docs, "README.md"))
        _write(os.path.join(self.docs, "src", "main.py"))
        _write(os.path.join(self.docs, "src", "helper.py"))
        _write(os.path.join(self.docs, "notes"))
        self._scan()

        overview = catalog_service.project_overview(self.project_id)

        self.assertEqual(overview["file_count"], 4)
        self.assertEqual(overview["by_type"], {"py": 2, "md": 1, "other": 1})
        self.assertEqual(
            [file["path"] for file in overview["files"]],
            [
                os.path.join(self.docs, "README.md"),
                os.path.join(self.docs, "notes"),
                os.path.join(self.docs, "src", "helper.py"),
                os.path.join(self.docs, "src", "main.py"),
            ],
        )
        self.assertFalse(overview["truncated"])

    def test_project_overview_lists_recent_catalog_changes(self):
        _write(os.path.join(self.docs, "old.txt"))
        self._scan()

        time.sleep(1.1)
        _write(os.path.join(self.docs, "new.txt"))
        self._scan()

        overview = catalog_service.project_overview(self.project_id, recent_limit=1)

        self.assertEqual(overview["recent_changes"][0]["path"], os.path.join(self.docs, "new.txt"))

    def test_project_overview_uses_catalog_not_current_disk(self):
        _write(os.path.join(self.docs, "kept.txt"))
        self._scan()
        os.remove(os.path.join(self.docs, "kept.txt"))

        overview = catalog_service.project_overview(self.project_id)

        self.assertEqual(overview["file_count"], 1)
        self.assertEqual(overview["files"][0]["name"], "kept.txt")


class IdentityTests(CatalogTestCase):
    def test_moving_a_file_into_a_subfolder_keeps_its_identity(self):
        _write(os.path.join(self.docs, "notes.txt"))
        self._scan()
        file_id = self._catalog()["notes.txt"]

        os.makedirs(os.path.join(self.docs, "archive"))
        os.rename(os.path.join(self.docs, "notes.txt"), os.path.join(self.docs, "archive", "notes.txt"))
        self._scan()

        self.assertEqual(self._catalog(), {"archive/notes.txt": file_id})

    def test_a_file_replaced_by_a_safe_save_keeps_its_identity(self):
        path = os.path.join(self.docs, "report.docx")
        _write(path, "v1")
        self._scan()
        file_id = self._catalog()["report.docx"]

        # Editors such as Word write a new file and rename it over the old one, which gives it a new OS identifier.
        _write(path + ".tmp", "version two")
        os.replace(path + ".tmp", path)
        self._scan()

        self.assertEqual(self._catalog(), {"report.docx": file_id})
        self.assertEqual(database.list_catalog_files(self.project_id)[0]["size"], len("version two"))

    def test_without_os_identifiers_a_renamed_file_is_found_by_its_content(self):
        _write(os.path.join(self.docs, "a.txt"), "unique contents")
        _write(os.path.join(self.docs, "b.txt"), "other contents")
        with patch.object(scanner, "_file_id", return_value=None):
            self._scan()
            ids = self._catalog()
            os.rename(os.path.join(self.docs, "a.txt"), os.path.join(self.docs, "renamed.txt"))
            self._scan()

        self.assertEqual(self._catalog(), {"renamed.txt": ids["a.txt"], "b.txt": ids["b.txt"]})

    def test_a_new_file_gets_a_new_identity_and_a_deleted_one_is_removed(self):
        _write(os.path.join(self.docs, "old.txt"))
        self._scan()
        old_id = self._catalog()["old.txt"]

        # Created before the old file is deleted: Linux gives a freed inode to the next new file, which
        # would make this look like a rename (see the limitation in the scanner's header).
        _write(os.path.join(self.docs, "new.txt"))
        os.remove(os.path.join(self.docs, "old.txt"))
        result = self._scan()

        self.assertEqual(list(self._catalog()), ["new.txt"])
        self.assertNotEqual(self._catalog()["new.txt"], old_id)
        self.assertEqual((result["added"], result["removed"]), (1, 1))


class RecordTests(CatalogTestCase):
    def test_a_record_holds_name_type_size_and_dates(self):
        _write(os.path.join(self.docs, "Plan.Final.PDF"), "12345")

        self._scan()

        record = database.list_catalog_files(self.project_id)[0]
        self.assertEqual((record["name"], record["extension"], record["size"]), ("Plan.Final.PDF", "pdf", 5))
        self.assertRegex(record["file_modified_at"], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$")
        if os.name == "nt":
            self.assertIsNotNone(record["file_created_at"])

    def test_the_ignore_rules_apply_to_folders_sensitive_files_and_binaries(self):
        _write(os.path.join(self.docs, "keep.txt"))
        _write(os.path.join(self.docs, "photos.zip"))
        _write(os.path.join(self.docs, ".git", "config"))
        _write(os.path.join(self.docs, "app", "node_modules", "lib.js"))
        _write(os.path.join(self.docs, ".claude.json"))

        self._scan()

        self.assertEqual(set(self._catalog()), {"keep.txt"})

    def test_links_and_junctions_are_not_followed(self):
        outside = os.path.join(self.tmpdir, "secret")
        _write(os.path.join(outside, "keys.txt"))
        _write(os.path.join(self.docs, "mine.txt"))
        _link_folder(os.path.join(self.docs, "shortcut"), outside)

        self._scan()

        self.assertEqual(list(self._catalog()), ["mine.txt"])

    def test_an_unreadable_folder_keeps_its_records(self):
        _write(os.path.join(self.docs, "notes.txt"))
        self._scan()
        file_id = self._catalog()["notes.txt"]

        with patch.object(scanner.os, "scandir", side_effect=PermissionError("no access")):
            result = self._scan()

        self.assertEqual(self._catalog(), {"notes.txt": file_id})
        self.assertEqual(result["unreadable_folders"], [self.docs])

    def test_each_project_has_its_own_records_and_loses_them_when_deleted(self):
        _write(os.path.join(self.docs, "shared.txt"))
        other_id = database.create_project("Taxes", folders=[(self.docs, "read")])["id"]
        self._scan()
        self._scan(other_id)

        self.assertNotEqual(self._catalog()["shared.txt"], self._catalog(other_id)["shared.txt"])
        database.delete_project(other_id)
        self.assertEqual(self._catalog(other_id), {})
        self.assertEqual(list(self._catalog()), ["shared.txt"])

    def test_a_cancelled_scan_leaves_the_catalog_unchanged(self):
        _write(os.path.join(self.docs, "a.txt"))
        self._scan()
        before = self._catalog()
        _write(os.path.join(self.docs, "b.txt"))
        job_id = database.enqueue_job(catalog_service.CATALOG_KIND, {"project_id": self.project_id}, self.project_id)
        with database._transaction() as conn:  # a running job that was asked to stop
            conn.execute("UPDATE jobs SET state = 'running', cancel_requested = 1 WHERE id = ?", (job_id,))

        with self.assertRaises(worker.JobCancelled):
            catalog_service.run_catalog_job({"project_id": self.project_id}, worker.JobContext(job_id))

        self.assertEqual(self._catalog(), before)


class CatalogRouteTests(CatalogTestCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app, headers={"Authorization": f"Bearer {API_TOKEN}"})

    def test_a_scan_is_queued_as_a_job_for_the_project(self):
        response = self.client.post(f"/projects/{self.project_id}/catalog")

        self.assertEqual(response.status_code, 202)
        job = response.json()
        self.assertEqual((job["kind"], job["project"], job["state"]), ("catalog", self.project_id, "queued"))

    def test_the_catalog_lists_the_scanned_files(self):
        _write(os.path.join(self.docs, "notes.md"))
        self._scan()

        files = self.client.get(f"/projects/{self.project_id}/catalog").json()

        self.assertEqual([(f["name"], f["extension"]) for f in files], [("notes.md", "md")])
        self.assertNotIn("file_key", files[0])
        self.assertEqual(self.client.get(f"/projects/{self.project_id}").json()["file_count"], 1)

    def test_an_unknown_project_returns_404(self):
        self.assertEqual(self.client.post("/projects/missing/catalog").status_code, 404)
        self.assertEqual(self.client.get("/projects/missing/catalog").status_code, 404)


if __name__ == "__main__":
    unittest.main()
