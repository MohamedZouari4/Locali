"""Tamper-evident action log: one line per file action, each hashed together with the line before it.

LOG_FILE is the authoritative record. Every entry is also mirrored into the database audit_log
table so it can be queried.
"""

import datetime
import getpass
import hashlib
import os
import socket
import stat

from app.core.config import LOG_FILE

GENESIS_HASH = "0" * 64


def _last_hash():
    if not os.path.exists(LOG_FILE):
        return GENESIS_HASH
    with open(LOG_FILE, encoding="utf-8") as f:
        lines = f.readlines()
    if not lines or " | hash=" not in lines[-1]:
        return GENESIS_HASH
    return lines[-1].strip().rsplit(" | hash=", 1)[1]


def log_action(action, target_path=None, success=True):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"
    host = socket.gethostname()
    entry = f"{datetime.datetime.now().isoformat()} - user={user} host={host} pid={os.getpid()} - {action}"
    entry_hash = hashlib.sha256((_last_hash() + entry).encode("utf-8")).hexdigest()

    if os.path.exists(LOG_FILE):
        os.chmod(LOG_FILE, stat.S_IWRITE)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{entry} | hash={entry_hash}\n")
    os.chmod(LOG_FILE, stat.S_IREAD)

    # Queryable mirror only — the hash-chained file above remains the
    # authoritative, tamper-evident record. A failure here must never
    # affect the real log, so it's isolated and silently ignored.
    try:
        from app.db.database import get_connection

        conn = get_connection()
        conn.execute(
            "INSERT INTO audit_log (action, target_path, result, success) VALUES (?, ?, ?, ?)",
            (action, target_path, action, success),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def verify_log_integrity():
    """Walk LOG_FILE's hash chain. Returns (True, None) if intact,
    or (False, line_number) for the first line where the chain breaks."""
    if not os.path.exists(LOG_FILE):
        return True, None
    with open(LOG_FILE, encoding="utf-8") as f:
        lines = f.readlines()
    prev_hash = GENESIS_HASH
    for i, raw in enumerate(lines, start=1):
        line = raw.rstrip("\n")
        if " | hash=" not in line:
            return False, i
        entry, claimed_hash = line.rsplit(" | hash=", 1)
        if hashlib.sha256((prev_hash + entry).encode("utf-8")).hexdigest() != claimed_hash:
            return False, i
        prev_hash = claimed_hash
    return True, None
