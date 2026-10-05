"""Decides which files ingestion may read: walks the scan roots while skipping system, privacy,
ignored and sensitive paths, and checks whether an indexed path is still in scope.

The scan roots are the folders chosen in the app (the indexed_folders table) plus SCAN_DRIVES from
config. Settings are read from `config` at call time, so changing them (for example in tests) takes effect.
"""

import os

from app.core import config
from app.db import database


def _norm(path):
    return os.path.abspath(path).replace("\\", "/").rstrip("/")


def _key(path):
    # Like _norm, but case-insensitive on Windows. normcase also turns slashes into backslashes there,
    # so it runs before they are turned into "/".
    return os.path.normcase(os.path.abspath(path)).replace(os.sep, "/").rstrip("/")


def is_under(path, folder):
    """True if path is folder itself or anything inside it (case-insensitively on Windows)."""
    path_key, folder_key = _key(path), _key(folder)
    return path_key == folder_key or path_key.startswith(folder_key + "/")


def scan_roots():
    """The folders ingestion walks: those chosen in the app, then SCAN_DRIVES, without duplicates."""
    roots = []
    for root in [folder["path"] for folder in database.list_indexed_folders()] + list(config.SCAN_DRIVES):
        if not any(is_under(root, kept) and is_under(kept, root) for kept in roots):
            roots.append(root)
    return roots


def exclusion_reason(path):
    """Why files at this path may never be read (a system, privacy or ignored folder), or None.

    The reason is worded to follow "can't be indexed because", for messages shown to the user.
    """
    norm = _norm(path)
    for excluded in config.SYSTEM_EXCLUDE:
        excluded_norm = _norm(excluded)
        if norm == excluded_norm or norm.startswith(excluded_norm + "/"):
            return f"it is a system folder ({excluded})"
    for private in config.PRIVACY_EXCLUDE:
        if private in norm:
            return f"it holds private app data ({private})"
    for part in norm.split("/"):
        if part in config.IGNORE_DIRS:
            return f"it is inside a folder that is never indexed ({part})"
    return None


def walk_data_dir(scan_drives):
    system_excludes = [_norm(ex) for ex in config.SYSTEM_EXCLUDE]
    for drive in scan_drives:
        for dirpath, dirnames, filenames in os.walk(drive):
            norm = _norm(dirpath)

            if any(norm == ex or norm.startswith(ex + "/") for ex in system_excludes):
                dirnames[:] = []
                continue
            if any(priv in norm for priv in config.PRIVACY_EXCLUDE):
                dirnames[:] = []
                continue

            dirnames[:] = [d for d in dirnames if d not in config.IGNORE_DIRS]
            for name in filenames:
                if name in config.SENSITIVE_FILES:
                    continue
                yield os.path.join(dirpath, name)


def is_excluded_path(path, roots):
    """True if path falls under any current exclusion rule (system/privacy/ignored dir/skip extension)
    or outside `roots` (from scan_roots()). Used to prune stale index entries left over from a
    previous, broader set of folders or exclusion rules.
    """
    if not any(is_under(path, root) for root in roots):
        return True
    if exclusion_reason(path):
        return True
    return _norm(path).rsplit(".", 1)[-1].lower() in config.SKIP_EXTENSIONS
