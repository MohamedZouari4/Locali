from fileinput import filename
import os
import shutil
import datetime
import getpass
import socket
import stat
import hashlib
from app.config import ALLOWED_ROOT, LOG_FILE

GENESIS_HASH = "0" * 64

def is_safe_path (path):
    target = os.path.realpath(path)
    root = os.path.realpath(ALLOWED_ROOT)
    try:
        return os.path.commonpath([target, root]) == root
    except ValueError:
        return False
    
def list_files (path="."):
    full_path = os.path.join(ALLOWED_ROOT, path)
    if not is_safe_path(full_path):
        raise PermissionError(f"Access to path '{full_path}' is not allowed.")

    if not os.path.exists(full_path):
        raise FileNotFoundError(f"Path '{full_path}' does not exist.")
    if not os.path.isdir(full_path):
        raise NotADirectoryError(f"Path '{full_path}' is not a directory.")

    return os.listdir(full_path)

def _last_hash():
    if not os.path.exists(LOG_FILE):
        return GENESIS_HASH
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if not lines or " | hash=" not in lines[-1]:
        return GENESIS_HASH
    return lines[-1].strip().rsplit(" | hash=", 1)[1]

def _log(action):
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
        from app.database import get_connection
        conn = get_connection()
        conn.execute(
            "INSERT INTO audit_log (action, target_path, result, success) VALUES (?, ?, ?, ?)",
            (action, None, action, True)
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
    with open(LOG_FILE, "r", encoding="utf-8") as f:
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

def move_file(src, dst):
    """Move a file from src to dst, both relative to ALLOWED_ROOT."""
    src_full = os.path.join(ALLOWED_ROOT, src)
    dst_full = os.path.join(ALLOWED_ROOT, dst)

    if not is_safe_path(src_full):
        raise PermissionError(f"Source path outside allowed workspace: {src}")
    if not is_safe_path(dst_full):
        raise PermissionError(f"Destination path outside allowed workspace: {dst}")

    if not os.path.isfile(src_full):
        raise FileNotFoundError(f"Source file does not exist: {src}")

    os.makedirs(os.path.dirname(dst_full), exist_ok=True)
    shutil.move(src_full, dst_full)
    _log(f"moved '{src}' -> '{dst}'")
    return f"Moved {src} to {dst}"

def create_folder(path):
    """Create a folder at the specified path relative to ALLOWED_ROOT."""
    full_path = os.path.join(ALLOWED_ROOT, path)

    if not is_safe_path(full_path):
        raise PermissionError(f"Path outside allowed workspace: {path}")

    os.makedirs(full_path, exist_ok=True)
    _log(f"created folder '{path}'")
    return f"Folder '{path}' created successfully."

def organize_by_extension(folder="."):
    """Organize files in the specified directory by their extensions."""
    full_path = os.path.join(ALLOWED_ROOT, folder)

    if not is_safe_path(full_path):
        raise PermissionError(f"Path outside allowed workspace: {folder}")
    if not os.path.isdir(full_path):
        raise NotADirectoryError(f"Path '{full_path}' is not a directory.")

    moved = 0
    for name in os.listdir(full_path):
        item_path = os.path.join(full_path, name)
        if os.path.isfile(item_path):
            ext = os.path.splitext(name)[1].lstrip(".").lower() or "no_extension"
            rel_src = os.path.join(folder, name) if folder != "." else name
            rel_dst = os.path.join(folder, ext, name) if folder != "." else os.path.join(ext, name)
            move_file(rel_src, rel_dst)
            moved += 1
            
    _log(f"organized {moved} files in '{folder}' by extension")
    return f"Files in '{folder}' organized by extension."

def find_empty_files(folder="."):
    """List files with zero bytes inside a folder within ALLOWED_ROOT."""
    full_path = os.path.join(ALLOWED_ROOT, folder)

    if not is_safe_path(full_path):
        raise PermissionError(f"Path outside allowed workspace: {folder}")
    if not os.path.isdir(full_path):
        raise FileNotFoundError(f"Not a directory: {folder}")

    empty = []
    for root, dirs, files in os.walk(full_path):
        for name in files:
            path = os.path.join(root, name)
            if os.path.getsize(path) == 0:
                empty.append(os.path.relpath(path, ALLOWED_ROOT))

    _log(f"searched '{folder}' for empty files, found {len(empty)}")
    return empty

