"""Tests for the /projects routes: creating, editing and deleting projects and their folders, which
folders are refused, and that deleting a project removes its chats but never real files.
Uses a temporary database and folders.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.main import app
from app.core import config
from app.core.security import API_TOKEN
from app.db import database


class ProjectRouteTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="project_routes_test_")
        self.docs = self._mkdir("docs")
        self._patches = [
            patch.object(database, "DB_PATH", os.path.join(self.tmpdir, "assistant_test.db")),
            patch.object(database, "_initialized", False),
            # The temp folder may sit under AppData, which is never indexed; tests set their own rules.
            patch.object(config, "SYSTEM_EXCLUDE", [os.path.join(self.tmpdir, "Windows")]),
            patch.object(config, "PRIVACY_EXCLUDE", ["Google/Chrome"]),
            patch.object(config, "IGNORE_DIRS", {".git"}),
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

    def _create(self, name="Thesis", instructions=""):
        return self.client.post("/projects", json={"name": name, "instructions": instructions})

    def _add_folder(self, project_id, path, permission="read"):
        return self.client.post(f"/projects/{project_id}/folders", json={"path": path, "permission": permission})


class ProjectTests(ProjectRouteTestCase):
    def test_a_project_is_created_listed_and_opened(self):
        response = self._create("  Thesis  ", "Answer in French.")

        self.assertEqual(response.status_code, 201)
        project = response.json()
        self.assertEqual((project["name"], project["instructions"], project["folders"]), ("Thesis", "Answer in French.", []))
        self.assertEqual([p["id"] for p in self.client.get("/projects").json()], [project["id"]])
        self.assertEqual(self.client.get(f"/projects/{project['id']}").json(), project)

    def test_instructions_and_name_are_edited_separately(self):
        project_id = self._create("Thesis", "Answer in French.").json()["id"]

        edited = self.client.patch(f"/projects/{project_id}", json={"instructions": "Be brief."}).json()
        renamed = self.client.patch(f"/projects/{project_id}", json={"name": "Master thesis"}).json()

        self.assertEqual((edited["name"], edited["instructions"]), ("Thesis", "Be brief."))
        self.assertEqual((renamed["name"], renamed["instructions"]), ("Master thesis", "Be brief."))

    def test_a_name_already_used_is_refused(self):
        self._create("Thesis")
        other_id = self._create("Taxes").json()["id"]

        self.assertEqual(self._create("THESIS").status_code, 409)
        self.assertEqual(self.client.patch(f"/projects/{other_id}", json={"name": "thesis"}).status_code, 409)

    def test_a_blank_name_is_refused(self):
        self.assertEqual(self._create("   ").status_code, 422)

    def test_an_unknown_project_is_404(self):
        self.assertEqual(self.client.get("/projects/missing").status_code, 404)
        self.assertEqual(self.client.patch("/projects/missing", json={"instructions": "x"}).status_code, 404)
        self.assertEqual(self.client.delete("/projects/missing").status_code, 404)
        self.assertEqual(self._add_folder("missing", self.docs).status_code, 404)

    def test_the_routes_require_the_token(self):
        self.assertEqual(TestClient(app).get("/projects").status_code, 401)


class ProjectFolderTests(ProjectRouteTestCase):
    def setUp(self):
        super().setUp()
        self.project_id = self._create().json()["id"]

    def test_folders_are_added_changed_and_removed(self):
        docs = self._add_folder(self.project_id, self.docs).json()
        self._add_folder(self.project_id, self._mkdir("drafts"), "act")

        changed = self.client.patch(f"/projects/{self.project_id}/folders/{docs['id']}", json={"permission": "act"})
        self.assertEqual(changed.json()["permission"], "act")

        self.assertEqual(self.client.delete(f"/projects/{self.project_id}/folders/{docs['id']}").status_code, 204)
        folders = self.client.get(f"/projects/{self.project_id}").json()["folders"]
        self.assertEqual([(f["path"], f["permission"]) for f in folders], [(os.path.join(self.tmpdir, "drafts"), "act")])
        self.assertTrue(os.path.isdir(self.docs))

    def test_refused_folders_say_why(self):
        cases = {
            "docs": "Choose a folder with a full path",
            os.path.join(self.tmpdir, "missing"): "doesn't exist or isn't a folder",
            self._mkdir("Windows", "System32"): "it is a system folder",
            self._mkdir("Profile", "Google", "Chrome"): "it holds private app data",
            self._mkdir("code", ".git"): "it is inside a folder that is never indexed (.git)",
        }
        for path, message in cases.items():
            with self.subTest(path=path):
                response = self._add_folder(self.project_id, path)
                self.assertEqual(response.status_code, 422)
                self.assertIn(message, response.json()["detail"])
        self.assertEqual(self.client.get(f"/projects/{self.project_id}").json()["folders"], [])

    def test_a_folder_already_in_the_project_is_refused(self):
        self._add_folder(self.project_id, self.docs)

        response = self._add_folder(self.project_id, self.docs.upper() if os.name == "nt" else self.docs)

        self.assertEqual(response.status_code, 422)
        self.assertIn("is already in this project", response.json()["detail"])

    def test_an_unknown_permission_is_refused(self):
        self.assertEqual(self._add_folder(self.project_id, self.docs, "write").status_code, 422)

    def test_a_folder_of_another_project_is_404(self):
        other_id = self._create("Taxes").json()["id"]
        folder_id = self._add_folder(other_id, self.docs).json()["id"]

        self.assertEqual(self.client.delete(f"/projects/{self.project_id}/folders/{folder_id}").status_code, 404)
        self.assertEqual(self.client.patch(f"/projects/{self.project_id}/folders/{folder_id}", json={"permission": "act"}).status_code, 404)


class DeleteProjectTests(ProjectRouteTestCase):
    def test_deleting_a_project_removes_its_chats_and_never_real_files(self):
        notes = os.path.join(self.docs, "notes.md")
        with open(notes, "w", encoding="utf-8") as f:
            f.write("keep me")
        project_id = self._create().json()["id"]
        self._add_folder(project_id, self.docs, "act")
        in_project, _ = database.begin_turn(None, "hello", project_id=project_id)
        outside, _ = database.begin_turn(None, "hi")

        self.assertEqual(self.client.delete(f"/projects/{project_id}").status_code, 204)

        self.assertEqual(self.client.get(f"/projects/{project_id}").status_code, 404)
        self.assertEqual(self.client.get(f"/conversations/{in_project}").status_code, 404)
        self.assertEqual(database.get_messages(in_project), [])
        self.assertEqual(self.client.get(f"/conversations/{outside}").status_code, 200)
        with open(notes, encoding="utf-8") as f:
            self.assertEqual(f.read(), "keep me")


if __name__ == "__main__":
    unittest.main()
