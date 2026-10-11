"""Tests for the ignore rules (P1-E2-T3): the default lists keep dependency and cache folders out of the
catalog and sensitive files unread, each project can add its own patterns (also applied to watcher
changes), and the skipped counts are saved and shown on the project. Uses a temporary database and
folders, and the real default ignore lists.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.ai.ingestion import pipeline, walker
from app.api.main import app
from app.catalog import scanner
from app.core import config
from app.core.config import PrivacySettings
from app.core.security import API_TOKEN
from app.db import database
from app.services import catalog_service

DEFAULTS = PrivacySettings()


def _write(path, text="hello"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class IgnoreRulesTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="ignore_rules_test_")
        self.docs = os.path.join(self.tmpdir, "docs")
        os.makedirs(self.docs)
        # The real default lists, minus names in the temp folder's own path (it may sit under AppData).
        ignore_dirs = {name for name in DEFAULTS.ignore_dirs if name not in Path(self.tmpdir).parts}
        self._patches = [
            patch.object(database, "DB_PATH", os.path.join(self.tmpdir, "assistant_test.db")),
            patch.object(database, "_initialized", False),
            patch.object(config, "SYSTEM_EXCLUDE", [os.path.join(self.tmpdir, "Windows")]),
            patch.object(config, "PRIVACY_EXCLUDE", ["Google/Chrome"]),
            patch.object(config, "IGNORE_DIRS", ignore_dirs),
            patch.object(config, "SENSITIVE_FILES", DEFAULTS.sensitive_files),
        ]
        for p in self._patches:
            p.start()
        self.project_id = database.create_project("Thesis", folders=[(self.docs, "read")])["id"]

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _set_patterns(self, patterns):
        database.update_project(self.project_id, ignore_patterns=patterns)

    def _scan(self):
        return catalog_service.catalog_project(database.get_project(self.project_id))

    def _catalog(self):
        files = database.list_catalog_files(self.project_id, limit=10000)
        return {os.path.relpath(f["path"], self.docs).replace(os.sep, "/") for f in files}


class AcceptanceTests(IgnoreRulesTestCase):
    def test_dependency_and_cache_folders_are_never_catalogued(self):
        folders = ["node_modules/lib", "__pycache__", ".venv/Lib", "venv", ".pytest_cache", ".mypy_cache", ".next/cache"]
        folders += ["dist", "build", "app/site-packages/pkg", ".git/objects", ".cache", "web/bower_components"]
        for folder in folders:
            _write(os.path.join(self.docs, folder, "file.js"))
        _write(os.path.join(self.docs, "src", "app.py"))

        result = self._scan()
        # A file the watcher reports inside one of them is skipped too.
        catalog_service.apply_changes(database.get_project(self.project_id), [os.path.join(self.docs, "node_modules", "lib", "file.js")])

        self.assertEqual(self._catalog(), {"src/app.py"})
        self.assertEqual(result["skipped"]["folders"], len(folders))

    def test_sensitive_files_are_never_read(self):
        names = [".env", ".env.local", "id_rsa", "ID_ED25519", "server.pem", "private.key", "credentials.json"]
        names += ["secrets.yaml", "vault.kdbx", ".git-credentials", "keystore.jks"]
        for name in names:
            _write(os.path.join(self.docs, "config", name), "token=secret")
        _write(os.path.join(self.docs, "notes.md"))

        # Without OS identifiers every catalogued file is hashed, which opens it: sensitive ones must not be.
        with patch.object(scanner, "_file_id", return_value=None), patch.object(scanner, "_hash", wraps=scanner._hash) as hashed:
            result = self._scan()
        walked = {os.path.basename(path) for path in walker.walk_data_dir([self.docs])}
        with patch.object(pipeline, "index_file") as index_file:
            pipeline.index_paths([os.path.join(self.docs, "config", name) for name in names])

        self.assertEqual(self._catalog(), {"notes.md"})
        self.assertEqual(result["skipped"]["sensitive"], len(names))
        self.assertEqual([os.path.basename(call.args[0]) for call in hashed.call_args_list], ["notes.md"])
        self.assertEqual(walked, {"notes.md"})
        index_file.assert_not_called()


class ProjectPatternTests(IgnoreRulesTestCase):
    def test_project_patterns_hide_matching_files_and_folders(self):
        self._set_patterns(["*.log", "drafts/", "data/raw/*.csv", "/notes"])
        for path in ["app.log", "sub/debug.LOG", "drafts/a.md", "data/raw/a.csv", "notes/n.md"]:
            _write(os.path.join(self.docs, path))
        for path in ["data/raw/b.txt", "data/a.csv", "sub/notes/n.md", "keep.md"]:
            _write(os.path.join(self.docs, path))

        result = self._scan()

        self.assertEqual(self._catalog(), {"data/raw/b.txt", "data/a.csv", "sub/notes/n.md", "keep.md"})
        self.assertEqual(result["skipped"]["project_rules"], 5)  # two logs, drafts/, one csv, notes/

    def test_a_pattern_never_hides_the_project_folder_itself(self):
        self._set_patterns(["docs"])
        _write(os.path.join(self.docs, "keep.md"))

        self._scan()

        self.assertEqual(self._catalog(), {"keep.md"})

    def test_watcher_changes_follow_the_project_patterns(self):
        self._set_patterns(["*.log", "drafts/"])
        paths = [os.path.join(self.docs, "app.log"), os.path.join(self.docs, "drafts", "a.md"), os.path.join(self.docs, "keep.md")]
        for path in paths:
            _write(path)

        catalog_service.apply_changes(database.get_project(self.project_id), paths)

        self.assertEqual(self._catalog(), {"keep.md"})

    def test_files_a_new_pattern_hides_leave_the_catalog(self):
        _write(os.path.join(self.docs, "app.log"))
        _write(os.path.join(self.docs, "keep.md"))
        self._scan()

        self._set_patterns(["*.log"])
        self._scan()

        self.assertEqual(self._catalog(), {"keep.md"})


class SkippedCountTests(IgnoreRulesTestCase):
    def test_skipped_counts_are_saved_on_the_project(self):
        self.assertIsNone(database.get_project(self.project_id)["catalog_skipped"])
        self._set_patterns(["*.tmp"])
        _write(os.path.join(self.docs, "node_modules", "x.js"))
        _write(os.path.join(self.docs, ".env"))
        _write(os.path.join(self.docs, "photos.zip"))
        _write(os.path.join(self.docs, "big.txt"), "x" * 2048)
        _write(os.path.join(self.docs, "scratch.tmp"))
        _write(os.path.join(self.docs, "keep.md"))

        with patch.object(config, "MAX_FILE_SIZE_MB", 0.001):  # about 1 KB
            self._scan()

        self.assertEqual(self._catalog(), {"keep.md"})
        self.assertEqual(
            database.get_project(self.project_id)["catalog_skipped"],
            {"folders": 1, "sensitive": 1, "binary": 1, "too_large": 1, "project_rules": 1},
        )


class PatternRouteTests(IgnoreRulesTestCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app, headers={"Authorization": f"Bearer {API_TOKEN}"})

    def _patch(self, patterns):
        return self.client.patch(f"/projects/{self.project_id}", json={"ignore_patterns": patterns})

    def test_patterns_are_cleaned_saved_and_start_a_scan(self):
        response = self._patch([" *.log ", "drafts\\", "*.log", ""])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ignore_patterns"], ["*.log", "drafts/"])
        jobs = [job for job in database.list_jobs(kind=catalog_service.CATALOG_KIND) if job["project"] == self.project_id]
        self.assertEqual(len(jobs), 1)

    def test_unchanged_patterns_start_no_scan(self):
        self._patch(["*.log"])
        self._patch(["*.log"])

        self.assertEqual(len(database.list_jobs(kind=catalog_service.CATALOG_KIND)), 1)

    def test_patterns_that_point_outside_the_project_are_refused(self):
        for pattern in ["C:/Windows", "../secret", "data/../../x", "//server/share"]:
            with self.subTest(pattern=pattern):
                self.assertEqual(self._patch([pattern]).status_code, 422)
        self.assertEqual(database.get_project(self.project_id)["ignore_patterns"], [])

    def test_the_project_shows_its_patterns_and_skipped_counts(self):
        self._patch(["*.log"])
        _write(os.path.join(self.docs, "app.log"))
        self._scan()

        project = self.client.get(f"/projects/{self.project_id}").json()

        self.assertEqual(project["ignore_patterns"], ["*.log"])
        self.assertEqual(project["catalog_skipped"]["project_rules"], 1)


if __name__ == "__main__":
    unittest.main()
