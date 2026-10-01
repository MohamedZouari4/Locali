"""Decides which files ingestion may read: walks the scan roots while skipping system, privacy,
ignored and sensitive paths, and checks whether an indexed path is still in scope.

Settings are read from `config` at call time, so changing them (for example in tests) takes effect.
"""

import os

from app.core import config


def _norm(path):
    return os.path.abspath(path).replace("\\", "/").rstrip("/")


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


def is_excluded_path(path):
    """True if path falls under any current exclusion rule (system/privacy/ignored dir/skip extension)
    or outside the configured scan roots. Used to prune stale index entries left over from a
    previous, broader SCAN_DRIVES/IGNORE_DIRS configuration.
    """
    norm = _norm(path)

    roots = [_norm(root) for root in config.SCAN_DRIVES]
    if not any(norm == root or norm.startswith(root + "/") for root in roots):
        return True
    excludes = [_norm(ex) for ex in config.SYSTEM_EXCLUDE]
    if any(norm == ex or norm.startswith(ex + "/") for ex in excludes):
        return True
    if any(priv in norm for priv in config.PRIVACY_EXCLUDE):
        return True
    if any(part in config.IGNORE_DIRS for part in norm.split("/")):
        return True
    return norm.rsplit(".", 1)[-1].lower() in config.SKIP_EXTENSIONS
