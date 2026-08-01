import os
import stat
import tempfile
import unittest
from unittest.mock import patch

import tools


def _make_writable(path):
    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            try:
                os.chmod(os.path.join(root, name), stat.S_IWRITE)
            except OSError:
                pass
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass


class SandboxTestCase(unittest.TestCase):
    """Base class that points ALLOWED_ROOT/LOG_FILE at a scratch temp dir."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp(prefix="tools_test_")
        self.root = os.path.realpath(self._tmpdir)
        self.log_file = os.path.join(self.root, "_logs", "actions.log")

        self._patches = [
            patch("tools.ALLOWED_ROOT", self.root),
            patch("tools.LOG_FILE", self.log_file),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        _make_writable(self._tmpdir)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)


# P1-E7-T1: is_safe_path() against valid, traversal, and absolute-path cases
class TestIsSafePath(SandboxTestCase):
    def test_valid_path_inside_root(self):
        target = os.path.join(self.root, "sub", "file.txt")
        self.assertTrue(tools.is_safe_path(target))

    def test_root_itself_is_safe(self):
        self.assertTrue(tools.is_safe_path(self.root))

    def test_traversal_escapes_root(self):
        target = os.path.join(self.root, "..", "..", "somewhere_else")
        self.assertFalse(tools.is_safe_path(target))

    def test_absolute_path_outside_root(self):
        outside = os.path.realpath(os.path.join(self.root, os.pardir, "definitely_outside"))
        self.assertFalse(tools.is_safe_path(outside))

    def test_sibling_dir_with_shared_prefix_is_unsafe(self):
        # e.g. root="C:\...\ws" vs "C:\...\ws_evil" must NOT be treated as inside root
        sibling = self.root + "_evil"
        self.assertFalse(tools.is_safe_path(sibling))


# P1-E7-T2: each tool function against a temporary allow-listed folder
class TestListFiles(SandboxTestCase):
    def test_lists_files_in_root(self):
        open(os.path.join(self.root, "a.txt"), "w").close()
        open(os.path.join(self.root, "b.txt"), "w").close()
        result = tools.list_files(".")
        self.assertEqual(sorted(result), ["a.txt", "b.txt"])

    def test_missing_path_raises(self):
        with self.assertRaises(FileNotFoundError):
            tools.list_files("does_not_exist")

    def test_file_instead_of_dir_raises(self):
        open(os.path.join(self.root, "f.txt"), "w").close()
        with self.assertRaises(NotADirectoryError):
            tools.list_files("f.txt")

    def test_traversal_raises_permission_error(self):
        with self.assertRaises(PermissionError):
            tools.list_files("../../outside")


class TestMoveFile(SandboxTestCase):
    def test_moves_file_and_creates_dest_dirs(self):
        open(os.path.join(self.root, "src.txt"), "w").close()
        tools.move_file("src.txt", "sub/dir/dst.txt")
        self.assertFalse(os.path.exists(os.path.join(self.root, "src.txt")))
        self.assertTrue(os.path.exists(os.path.join(self.root, "sub", "dir", "dst.txt")))

    def test_missing_source_raises(self):
        with self.assertRaises(FileNotFoundError):
            tools.move_file("nope.txt", "dst.txt")

    def test_source_outside_root_raises(self):
        with self.assertRaises(PermissionError):
            tools.move_file("../outside.txt", "dst.txt")

    def test_dest_outside_root_raises(self):
        open(os.path.join(self.root, "src.txt"), "w").close()
        with self.assertRaises(PermissionError):
            tools.move_file("src.txt", "../outside.txt")

    def test_logs_the_move(self):
        open(os.path.join(self.root, "src.txt"), "w").close()
        tools.move_file("src.txt", "dst.txt")
        self.assertTrue(os.path.exists(self.log_file))


class TestCreateFolder(SandboxTestCase):
    def test_creates_nested_folder(self):
        tools.create_folder("a/b/c")
        self.assertTrue(os.path.isdir(os.path.join(self.root, "a", "b", "c")))

    def test_idempotent_when_folder_exists(self):
        tools.create_folder("a")
        tools.create_folder("a")  # should not raise
        self.assertTrue(os.path.isdir(os.path.join(self.root, "a")))

    def test_outside_root_raises(self):
        with self.assertRaises(PermissionError):
            tools.create_folder("../outside_folder")


class TestOrganizeByExtension(SandboxTestCase):
    def test_sorts_files_by_extension(self):
        open(os.path.join(self.root, "a.txt"), "w").close()
        open(os.path.join(self.root, "b.jpg"), "w").close()
        open(os.path.join(self.root, "c"), "w").close()  # no extension

        tools.organize_by_extension(".")

        self.assertTrue(os.path.exists(os.path.join(self.root, "txt", "a.txt")))
        self.assertTrue(os.path.exists(os.path.join(self.root, "jpg", "b.jpg")))
        self.assertTrue(os.path.exists(os.path.join(self.root, "no_extension", "c")))

    def test_missing_dir_raises(self):
        with self.assertRaises(NotADirectoryError):
            tools.organize_by_extension("nope")

    def test_outside_root_raises(self):
        with self.assertRaises(PermissionError):
            tools.organize_by_extension("../outside")


class TestFindEmptyFiles(SandboxTestCase):
    def test_finds_zero_byte_files_recursively(self):
        open(os.path.join(self.root, "empty.txt"), "w").close()
        with open(os.path.join(self.root, "full.txt"), "w") as f:
            f.write("content")
        os.makedirs(os.path.join(self.root, "sub"))
        open(os.path.join(self.root, "sub", "empty2.txt"), "w").close()

        result = tools.find_empty_files(".")

        self.assertIn("empty.txt", result)
        self.assertIn(os.path.join("sub", "empty2.txt"), result)
        self.assertNotIn("full.txt", result)

    def test_outside_root_raises(self):
        with self.assertRaises(PermissionError):
            tools.find_empty_files("../outside")

    def test_missing_dir_raises(self):
        with self.assertRaises(FileNotFoundError):
            tools.find_empty_files("nope")

    # TestListFiles
    def test_missing_path_raises(self):
        with self.assertRaises(FileNotFoundError):
            tools.list_files("does_not_exist")

    # TestOrganizeByExtension  
    def test_missing_dir_raises(self):
        with self.assertRaises(NotADirectoryError):
            tools.organize_by_extension("nope")


if __name__ == "__main__":
    unittest.main()
