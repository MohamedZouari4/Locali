"""Catalog scanner: lists the files in a project's folders with their name, type, size and dates, and
matches them to the project's stored records so that every file keeps a stable identity (its record id).

The walk never follows symbolic links or junctions, so it can't leave the project's folders, and it
skips what IgnoreRules hides: system, private, dependency and cache folders (the default ignore lists),
files that may hold keys or credentials, programs, archives and media, files over MAX_FILE_SIZE_MB, and
whatever the project's own patterns match. Files are skipped by name and size only, so a sensitive file
is never opened. A full scan counts what it skipped, by reason.

A file is recognised, in this order, by:
1. the operating system's file identifier (volume and file ID on Windows, device and inode elsewhere),
   which stays the same when a file is renamed or moved within a volume;
2. its path, because an editor's "safe save" replaces a file with a new one under the same name;
3. its content hash, only on file systems without identifiers (st_ino is 0, as on some network
   drives), so a renamed file is still found there.

The walk follows the ingestion ignore rules (system, privacy and ignored folders, sensitive files) and
never follows symbolic links or junctions, so it can't leave the project's folders. Files with skipped
extensions are still listed: the catalog records that a file exists, not what it contains.
scan_changes builds a partial scan from the paths the file watcher reported; match then only removes
records under those paths.
"""

import fnmatch
import hashlib
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.ai.ingestion.walker import exclusion_reason, is_sensitive, is_under
from app.core import config

SKIP_REASONS = ("folders", "sensitive", "binary", "too_large", "project_rules")


@dataclass
class Scan:
    files: list = field(default_factory=list)  # one dict per file, see read_file()
    unreadable: list = field(default_factory=list)  # folders that couldn't be listed; their records are kept
    skipped: dict = field(default_factory=lambda: dict.fromkeys(SKIP_REASONS, 0))  # by reason, see IgnoreRules


class IgnoreRules:
    """What the catalog skips in one project: the default ignore lists from config, plus the project's own
    patterns. A pattern without a slash (*.log, drafts) matches a file or folder name anywhere; one with a
    slash (data/raw/*.csv, /notes) matches the path from the project folder; a trailing slash (drafts/)
    matches folders only. Names are compared ignoring case. A project folder itself is never hidden by a pattern.
    """

    def __init__(self, folders, patterns=()):
        self.folders = list(folders)
        self.patterns = [pattern.lower() for pattern in patterns]

    def _matches(self, path, is_dir):
        root = max((folder for folder in self.folders if is_under(path, folder)), key=len, default=None)
        if root is None or not self.patterns:
            return False
        relative = os.path.relpath(path, root).replace(os.sep, "/").lower()
        if relative == ".":
            return False
        name = os.path.basename(path).lower()
        for pattern in self.patterns:
            if pattern.endswith("/") and not is_dir:
                continue
            anchored = "/" in pattern.rstrip("/")
            if fnmatch.fnmatchcase(relative if anchored else name, pattern.strip("/")):
                return True
        return False

    def skip_folder(self, path):
        """The reason a folder is skipped with everything in it, or None."""
        if exclusion_reason(path):
            return "folders"
        if self._matches(path, is_dir=True):
            return "project_rules"
        return None

    def skip_file(self, path):
        """The reason a file is skipped, judged by its name only (it isn't opened), or None."""
        name = os.path.basename(path)
        if is_sensitive(name):
            return "sensitive"
        if "." in name and name.rsplit(".", 1)[-1].lower() in config.SKIP_EXTENSIONS:
            return "binary"
        if self._matches(path, is_dir=False):
            return "project_rules"
        return None

    def skip_changed(self, path, is_dir):
        """The reason a path the watcher reported is skipped, checking every folder above it up to and
        including its project folder, or None."""
        folder = os.path.dirname(path)
        while any(is_under(folder, root) for root in self.folders):
            if reason := self.skip_folder(folder):
                return reason
            if any(is_under(root, folder) for root in self.folders):
                break  # that was the project folder
            folder = os.path.dirname(folder)
        return self.skip_folder(path) if is_dir else self.skip_file(path)


def _too_large(file):
    return file["size"] > config.MAX_FILE_SIZE_MB * 1024 * 1024


def _timestamp(seconds):
    # The same UTC format as SQLite's CURRENT_TIMESTAMP, used by every other date in the database.
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%d %H:%M:%S")


def _path_key(path):
    return os.path.normcase(os.path.abspath(path))


def _file_id(stat):
    """The operating system's identifier for the file, or None if the file system doesn't provide one."""
    return f"os:{stat.st_dev}:{stat.st_ino}" if stat.st_ino else None


def read_file(path):
    """The catalog fields of one file. Uses os.stat, because DirEntry.stat leaves st_ino at 0 on Windows."""
    stat = os.stat(path)
    name = os.path.basename(path)
    created = getattr(stat, "st_birthtime", None)  # Windows and macOS only
    return {
        "path": path,
        "file_key": _file_id(stat) or f"path:{_path_key(path)}",
        "has_os_id": _file_id(stat) is not None,
        "name": name,
        "extension": os.path.splitext(name)[1].lstrip(".").lower(),
        "size": stat.st_size,
        "file_created_at": _timestamp(created) if created else None,
        "file_modified_at": _timestamp(stat.st_mtime),
        "content_hash": None,
    }


def scan(rules, report=None, start=None):
    """Walks the project's folders (an IgnoreRules), or only the `start` folders inside them, and returns
    a Scan. `report(count, folder)` is called after each file found; an exception it raises (such as a
    cancelled job) stops the walk."""
    result = Scan()
    seen = set()
    for root in start or rules.folders:
        stack = [root]
        while stack:
            folder = stack.pop()
            if reason := rules.skip_folder(folder):
                result.skipped[reason] += 1
                continue
            try:
                with os.scandir(folder) as entries:
                    entries = list(entries)
            except OSError:  # missing (an unplugged drive), or no permission
                result.unreadable.append(folder)
                continue
            for entry in entries:
                if entry.is_symlink() or entry.is_junction():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    key = _path_key(entry.path)
                    if key in seen:  # nested project folders reach the same file twice
                        continue
                    seen.add(key)
                    if reason := rules.skip_file(entry.path):
                        result.skipped[reason] += 1
                        continue
                    try:
                        file = read_file(entry.path)
                    except OSError:  # deleted since the folder was listed
                        continue
                    if _too_large(file):
                        result.skipped["too_large"] += 1
                        continue
                    result.files.append(file)
                    if report:
                        report(len(result.files), root)
    return result


def scan_changes(paths, rules):
    """A partial Scan of the changed paths inside the project's folders (an IgnoreRules), and the paths it
    covers (for match's `scope`). A path the rules hide stays in the scope, so it leaves the catalog.

    A changed folder is walked whole, since a folder moved in arrives as one event. A path that no longer
    exists stays in the scope, so its record, or every record under it if it was a folder, is removed
    unless the file turns up elsewhere in the same batch.
    """
    result = Scan()
    found = {}
    scope = []
    for path in paths:
        if not any(is_under(path, folder) for folder in rules.folders):
            continue
        scope.append(path)
        if os.path.islink(path) or os.path.isjunction(path):
            continue
        files = []
        if os.path.isdir(path):
            if rules.skip_changed(path, is_dir=True) is None:
                partial = scan(rules, start=[path])
                result.unreadable.extend(partial.unreadable)
                files = partial.files
        elif os.path.isfile(path) and rules.skip_changed(path, is_dir=False) is None:
            try:
                file = read_file(path)
                files = [] if _too_large(file) else [file]
            except OSError:  # deleted again since the event
                pass
        for file in files:
            found[_path_key(file["path"])] = file
    result.files = list(found.values())
    return result, scope


def _hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def match(records, scan, scope=None):
    """Pairs the scanned files with the stored records (dicts with id, file_key, path, size,
    file_modified_at and content_hash). Returns (updates, inserts, delete_ids, renamed): updates are
    file dicts with the id of their record, inserts are new files, and renamed counts records whose path changed.

    Records under a folder that couldn't be read are neither updated nor deleted.
    """
    by_key = {record["file_key"]: record for record in records}
    by_path = {_path_key(record["path"]): record for record in records}
    matched = {}  # record id -> file
    unmatched = []

    def pair(record, file):
        if record is None or record["id"] in matched:
            return False
        matched[record["id"]] = file
        return True

    for file in scan.files:
        if not pair(by_key.get(file["file_key"]), file):
            unmatched.append(file)
    unmatched = [file for file in unmatched if not pair(by_path.get(_path_key(file["path"])), file)]

    # Files without an OS identifier keep a content hash, so a rename can be found on the next scan.
    # It is only recomputed when the size or modification time changed.
    previous = {record["id"]: record for record in records}
    for record_id, file in matched.items():
        record = previous[record_id]
        if not file["has_os_id"]:
            same = (record["size"], record["file_modified_at"]) == (file["size"], file["file_modified_at"])
            file["content_hash"] = record["content_hash"] if same and record["content_hash"] else _hash(file["path"])
    by_hash = {record["content_hash"]: record for record in records if record["content_hash"] and record["id"] not in matched}
    inserts = []
    for file in unmatched:
        if not file["has_os_id"]:
            file["content_hash"] = _hash(file["path"])
            if pair(by_hash.pop(file["content_hash"], None), file):
                continue
        inserts.append(file)

    updates = [{**file, "id": record_id} for record_id, file in matched.items()]
    renamed = sum(1 for update in updates if _path_key(update["path"]) != _path_key(previous[update["id"]]["path"]))
    delete_ids = [
        record["id"]
        for record in records
        if record["id"] not in matched
        and not any(is_under(record["path"], folder) for folder in scan.unreadable)
        and (scope is None or any(is_under(record["path"], path) for path in scope))
    ]
    return updates, inserts, delete_ids, renamed
