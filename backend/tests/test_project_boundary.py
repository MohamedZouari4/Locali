"""Security tests for the project boundary (P1-E1-T5): every way out of a project's folders is refused.

Each test builds real folders in a temporary directory: the project folder Thesis, a Secret folder
next to it, and siblings whose names start like Thesis. Links are real symbolic links, or junctions on
Windows when symbolic links need a privilege the account doesn't have. Windows-only cases (letter case,
mixed separators, short names, device names, UNC paths) are skipped on other systems.
"""

import ctypes
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.db import database
from app.services import project_service
from app.services.project_boundary import PathRefused, check_path

WINDOWS = os.name == "nt"
OUTSIDE = "outside this project's folders"
LEADS_OUTSIDE = "leads outside this project's folders"


def _link_folder(link, target):
    """Makes `link` point at the folder `target`: a symbolic link, or a junction on Windows without the privilege."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if not WINDOWS:
            raise
        import _winapi

        _winapi.CreateJunction(target, link)


def _short_name(path):
    """The Windows 8.3 short name of an existing path, or None if the volume doesn't make them."""
    buffer = ctypes.create_unicode_buffer(1024)
    if not ctypes.windll.kernel32.GetShortPathNameW(path, buffer, len(buffer)):
        return None
    return buffer.value if buffer.value.lower() != path.lower() else None


class BoundaryTestCase(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp(prefix="boundary_test_"))
        self.thesis = self._folder("Thesis")
        self.secret = self._folder("Secret")
        self._file(self.thesis, "notes.txt")
        self._file(self.secret, "keys.txt")
        self.folders = [{"path": self.thesis, "permission": "read"}]

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def _folder(self, *parts):
        path = os.path.join(self.base, *parts)
        os.makedirs(path, exist_ok=True)
        return path

    def _file(self, folder, name):
        path = os.path.join(folder, name)
        with open(path, "w") as f:
            f.write("x")
        return path

    def assertAllowed(self, path, folders=None):
        resolved, folder = check_path(path, folders or self.folders)
        return resolved, folder

    def assertRefused(self, path, reason=OUTSIDE, folders=None):
        with self.assertRaisesRegex(PathRefused, reason, msg=f"{path!r} was not refused"):
            check_path(path, folders or self.folders)


class TraversalTests(BoundaryTestCase):
    def test_dot_dot_out_to_a_neighbour_is_refused(self):
        self.assertRefused(os.path.join(self.thesis, "..", "Secret", "keys.txt"))

    def test_dot_dot_up_to_the_root_is_refused(self):
        self.assertRefused(os.path.join(self.thesis, *[".."] * 30))

    def test_dot_dot_from_a_subfolder_is_refused(self):
        drafts = self._folder("Thesis", "drafts")
        self.assertRefused(os.path.join(drafts, "..", "..", "Secret", "keys.txt"))

    def test_dot_dot_through_a_folder_that_does_not_exist_is_refused(self):
        self.assertRefused(os.path.join(self.thesis, "missing", "..", "..", "Secret", "keys.txt"))

    def test_dot_dot_written_with_forward_slashes_is_refused(self):
        self.assertRefused(self.thesis.replace(os.sep, "/") + "/../Secret/keys.txt")

    def test_dot_dot_that_stays_inside_is_allowed(self):
        drafts = self._folder("Thesis", "drafts")
        resolved, _ = self.assertAllowed(os.path.join(drafts, "..", "notes.txt"))
        self.assertEqual(resolved, os.path.join(self.thesis, "notes.txt"))

    def test_relative_paths_are_refused(self):
        for path in ["notes.txt", os.path.join("..", "Secret", "keys.txt"), os.path.join("Thesis", "..", "..")]:
            with self.subTest(path=path):
                self.assertRefused(path, "isn't a full path")


class AbsolutePathTests(BoundaryTestCase):
    def test_system_paths_are_refused(self):
        if WINDOWS:
            system_root = os.environ.get("SystemRoot", r"C:\Windows")
            paths = [
                system_root,
                os.path.join(system_root, "System32", "drivers", "etc", "hosts"),
                os.path.join(system_root, "System32", "config", "SAM"),
                os.path.splitdrive(self.base)[0] + "\\",
            ]
        else:
            paths = ["/", "/etc/passwd", "/etc/shadow", os.path.expanduser("~/.ssh/id_rsa")]
        for path in paths:
            with self.subTest(path=path):
                self.assertRefused(path)

    def test_the_folder_above_the_project_is_refused(self):
        self.assertRefused(self.base)

    def test_a_file_in_another_folder_is_refused(self):
        self.assertRefused(os.path.join(self.secret, "keys.txt"))

    @unittest.skipUnless(WINDOWS, "Windows path forms")
    def test_windows_special_path_forms_are_refused(self):
        drive = os.path.splitdrive(self.base)[0]
        for path in [
            r"\\server\share\notes.txt",
            "\\\\?\\" + os.path.join(self.secret, "keys.txt"),
            "\\\\.\\" + drive,
            "\\\\.\\PhysicalDrive0",
        ]:
            with self.subTest(path=path):
                self.assertRefused(path, "outside|reserves")

    @unittest.skipUnless(WINDOWS, "drive-relative paths only exist on Windows")
    def test_a_drive_relative_path_is_refused(self):
        drive = os.path.splitdrive(self.base)[0]
        self.assertRefused(drive + "notes.txt", "isn't a full path")

    @unittest.skipUnless(WINDOWS, "device names only exist on Windows")
    def test_device_names_inside_the_folder_are_refused(self):
        for name in ["CON", "nul", "con.txt", "COM1", "LPT1.log", "AUX.", "CONIN$", os.path.join("NUL", "x.txt")]:
            with self.subTest(name=name):
                self.assertRefused(os.path.join(self.thesis, name), "reserves for a device")

    @unittest.skipUnless(WINDOWS, "device names only exist on Windows")
    def test_names_that_only_start_like_a_device_are_allowed(self):
        for name in ["console.txt", "connect", "nullable.py", "COM10"]:
            with self.subTest(name=name):
                self.assertAllowed(os.path.join(self.thesis, name))

    def test_a_null_character_is_refused(self):
        self.assertRefused(os.path.join(self.thesis, "notes.txt\0..", "x"), "null character")

    def test_an_empty_path_is_refused(self):
        self.assertRefused("", "No path was given")

    def test_a_project_without_folders_refuses_everything(self):
        with self.assertRaisesRegex(PathRefused, "no folders"):
            check_path(os.path.join(self.thesis, "notes.txt"), [])


class LinkTests(BoundaryTestCase):
    def test_a_folder_link_inside_pointing_outside_is_refused(self):
        _link_folder(os.path.join(self.thesis, "escape"), self.secret)
        self.assertRefused(os.path.join(self.thesis, "escape"), LEADS_OUTSIDE)
        self.assertRefused(os.path.join(self.thesis, "escape", "keys.txt"), LEADS_OUTSIDE)

    def test_a_new_file_through_a_link_pointing_outside_is_refused(self):
        _link_folder(os.path.join(self.thesis, "escape"), self.secret)
        self.assertRefused(os.path.join(self.thesis, "escape", "new", "file.txt"), LEADS_OUTSIDE)

    def test_a_link_deep_inside_pointing_outside_is_refused(self):
        deep = self._folder("Thesis", "a", "b", "c")
        _link_folder(os.path.join(deep, "escape"), self.secret)
        self.assertRefused(os.path.join(deep, "escape", "keys.txt"), LEADS_OUTSIDE)

    def test_a_link_pointing_at_the_drive_root_is_refused(self):
        _link_folder(os.path.join(self.thesis, "root"), os.path.abspath(os.sep))
        self.assertRefused(os.path.join(self.thesis, "root"), LEADS_OUTSIDE)

    def test_a_chain_of_links_ending_outside_is_refused(self):
        _link_folder(os.path.join(self.thesis, "second"), self.secret)
        _link_folder(os.path.join(self.thesis, "first"), os.path.join(self.thesis, "second"))
        self.assertRefused(os.path.join(self.thesis, "first", "keys.txt"), LEADS_OUTSIDE)

    def test_a_link_pointing_to_a_sibling_with_a_similar_name_is_refused(self):
        sibling = self._folder("Thesis-old")
        _link_folder(os.path.join(self.thesis, "old"), sibling)
        self.assertRefused(os.path.join(self.thesis, "old", "a.txt"), LEADS_OUTSIDE)

    def test_a_file_link_inside_pointing_outside_is_refused(self):
        link = os.path.join(self.thesis, "keys.txt")
        try:
            os.symlink(os.path.join(self.secret, "keys.txt"), link)
        except OSError:
            self.skipTest("creating file symbolic links needs Developer Mode or admin rights here")
        self.assertRefused(link, LEADS_OUTSIDE)

    def test_a_link_that_stays_inside_is_allowed(self):
        drafts = self._folder("Thesis", "drafts")
        _link_folder(os.path.join(self.thesis, "shortcut"), drafts)
        resolved, _ = self.assertAllowed(os.path.join(self.thesis, "shortcut", "a.md"))
        self.assertEqual(resolved, os.path.join(drafts, "a.md"))

    def test_a_project_folder_that_is_itself_a_link_still_holds(self):
        linked = os.path.join(self.base, "Thesis-link")
        _link_folder(linked, self.thesis)
        folders = [{"path": linked, "permission": "read"}]
        self.assertAllowed(os.path.join(linked, "notes.txt"), folders)
        self.assertAllowed(os.path.join(self.thesis, "notes.txt"), folders)
        self.assertRefused(os.path.join(linked, "..", "Secret", "keys.txt"), folders=folders)


class SiblingTests(BoundaryTestCase):
    def test_siblings_whose_names_start_like_the_project_folder_are_refused(self):
        for name in ["Thesis-old", "Thesis2", "Thesis old", "Thesis.bak", "Thesis_evil", "Thesisx"]:
            sibling = self._folder(name)
            with self.subTest(name=name):
                self.assertRefused(sibling)
                self.assertRefused(self._file(sibling, "a.txt"))

    def test_a_sibling_that_does_not_exist_yet_is_refused(self):
        self.assertRefused(self.thesis + "-new" + os.sep + "a.txt")

    def test_a_sibling_is_refused_when_the_folder_is_stored_with_a_trailing_separator(self):
        sibling = self._folder("Thesis-old")
        folders = [{"path": self.thesis + os.sep, "permission": "read"}]
        self.assertRefused(os.path.join(sibling, "a.txt"), folders=folders)

    def test_a_project_folder_does_not_cover_its_parent_sibling_folders(self):
        drafts = self._folder("Thesis", "drafts")
        folders = [{"path": drafts, "permission": "act"}]
        self.assertRefused(os.path.join(self.thesis, "notes.txt"), folders=folders)
        self.assertRefused(self._folder("Thesis", "drafts-old"), folders=folders)


class CaseAndSeparatorTests(BoundaryTestCase):
    def test_trailing_separators_are_allowed(self):
        for path in [self.thesis + os.sep, self.thesis + os.sep * 2, os.path.join(self.thesis, "sub") + os.sep]:
            with self.subTest(path=path):
                self.assertAllowed(path)

    def test_a_folder_stored_with_a_trailing_separator_still_matches(self):
        folders = [{"path": self.thesis + os.sep, "permission": "read"}]
        self.assertAllowed(os.path.join(self.thesis, "notes.txt"), folders)

    def test_trailing_separators_do_not_help_a_sibling_or_traversal(self):
        sibling = self._folder("Thesis-old")
        self.assertRefused(sibling + os.sep)
        self.assertRefused(os.path.join(self.thesis, "..") + os.sep)

    @unittest.skipUnless(WINDOWS, "Windows paths ignore letter case")
    def test_other_letter_case_is_allowed(self):
        for path in [self.thesis.upper(), os.path.join(self.thesis.lower(), "NOTES.TXT"), self.thesis.swapcase() + "\\"]:
            with self.subTest(path=path):
                self.assertAllowed(path)

    @unittest.skipUnless(WINDOWS, "Windows paths ignore letter case")
    def test_other_letter_case_does_not_help_an_escape(self):
        sibling = self._folder("Thesis-old")
        self.assertRefused(sibling.upper())
        self.assertRefused(os.path.join(self.thesis.upper(), "..", "SECRET", "KEYS.TXT"))
        self.assertRefused(self.secret.lower())

    @unittest.skipUnless(WINDOWS, "mixed separators are a Windows thing")
    def test_mixed_separators_are_allowed_inside_and_refused_outside(self):
        self.assertAllowed(self.thesis.replace("\\", "/") + "\\notes.txt")
        self.assertAllowed(self.thesis + "/sub\\file.txt/")
        self.assertRefused(self.thesis.replace("\\", "/") + "/..\\Secret/keys.txt")

    @unittest.skipUnless(WINDOWS, "short (8.3) names are a Windows thing")
    def test_short_names_are_resolved(self):
        inside = self._folder("Thesis", "A rather long folder name")
        short_inside = _short_name(inside)
        short_secret = _short_name(self._folder("Secret folder with long name"))
        if not short_inside or not short_secret:
            self.skipTest("this volume doesn't create short names")
        self.assertAllowed(os.path.join(short_inside, "a.txt"))
        self.assertRefused(os.path.join(short_secret, "a.txt"))


class InnermostFolderTests(BoundaryTestCase):
    def test_the_innermost_folder_and_its_permission_are_returned(self):
        drafts = self._folder("Thesis", "drafts")
        folders = [{"path": self.thesis, "permission": "read"}, {"path": drafts, "permission": "act"}]

        _, outer = self.assertAllowed(os.path.join(self.thesis, "notes.txt"), folders)
        _, inner = self.assertAllowed(os.path.join(drafts, "chapter.md"), folders)

        self.assertEqual((outer["permission"], inner["permission"]), ("read", "act"))


class ProjectServiceTests(BoundaryTestCase):
    """The same check, reached through a project stored in a temporary database."""

    def setUp(self):
        super().setUp()
        self._patches = [
            patch.object(database, "DB_PATH", os.path.join(self.base, "assistant_test.db")),
            patch.object(database, "_initialized", False),
        ]
        for p in self._patches:
            p.start()
        self.project = database.create_project("Thesis", folders=[(self.thesis, "read")])

    def tearDown(self):
        for p in self._patches:
            p.stop()
        super().tearDown()

    def test_a_path_inside_the_project_returns_its_folder(self):
        _, folder = project_service.check_path(self.project["id"], os.path.join(self.thesis, "notes.txt"))
        self.assertEqual(folder["permission"], "read")

    def test_an_escape_is_refused_with_the_reason(self):
        with self.assertRaisesRegex(PathRefused, OUTSIDE):
            project_service.check_path(self.project["id"], os.path.join(self.thesis, "..", "Secret", "keys.txt"))

    def test_an_unknown_project_returns_none(self):
        self.assertIsNone(project_service.check_path("no-such-project", os.path.join(self.thesis, "notes.txt")))

    def test_a_project_without_folders_refuses_everything(self):
        empty = database.create_project("Empty")
        with self.assertRaisesRegex(PathRefused, "no folders"):
            project_service.check_path(empty["id"], os.path.join(self.thesis, "notes.txt"))


if __name__ == "__main__":
    unittest.main()
