"""Catalog scanner: lists the files in a project's folders with their name, type, size and dates, and
matches them to the project's stored records so that every file keeps a stable identity (its record id).

A file is recognised, in this order, by:
1. the operating system's file identifier (volume and file ID on Windows, device and inode elsewhere),
   which stays the same when a file is renamed or moved within a volume;
2. its path, because an editor's "safe save" replaces a file with a new one under the same name;
3. its content hash, only on file systems without identifiers (st_ino is 0, as on some network
   drives), so a renamed file is still found there.

The walk follows the ingestion ignore rules (system, privacy and ignored folders, sensitive files) and
never follows symbolic links or junctions, so it can't leave the project's folders. Files with skipped
extensions are still listed: the catalog records that a file exists, not what it contains.
"""

import hashlib
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.ai.ingestion.walker import exclusion_reason, is_under
from app.core import config


@dataclass
class Scan:
    files: list = field(default_factory=list)  # one dict per file, see read_file()
    unreadable: list = field(default_factory=list)  # folders that couldn't be listed; their records are kept


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


def scan(folders, report=None):
    """Walks the folders and returns a Scan. `report(count, folder)` is called after each file found;
    an exception it raises (such as a cancelled job) stops the walk."""
    result = Scan()
    seen = set()
    for root in folders:
        stack = [root]
        while stack:
            folder = stack.pop()
            if exclusion_reason(folder):
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
                elif entry.is_file(follow_symlinks=False) and entry.name not in config.SENSITIVE_FILES:
                    key = _path_key(entry.path)
                    if key in seen:  # nested project folders reach the same file twice
                        continue
                    seen.add(key)
                    try:
                        result.files.append(read_file(entry.path))
                    except OSError:  # deleted since the folder was listed
                        continue
                    if report:
                        report(len(result.files), root)
    return result


def _hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def match(records, scan):
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
        if record["id"] not in matched and not any(is_under(record["path"], folder) for folder in scan.unreadable)
    ]
    return updates, inserts, delete_ids, renamed
