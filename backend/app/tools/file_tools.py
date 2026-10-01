"""Sandboxed file tools (list, move, create folder, organize by extension, find empty files),
all restricted to ALLOWED_ROOT.

Every tool except list_files records its action in the hash-chained audit log.
"""

import os
import shutil

from app.core.config import ALLOWED_ROOT
from app.tools.audit_log import log_action


def is_safe_path(path):
    target = os.path.realpath(path)
    root = os.path.realpath(ALLOWED_ROOT)
    try:
        return os.path.commonpath([target, root]) == root
    except ValueError:
        return False


def list_files(path="."):
    full_path = os.path.join(ALLOWED_ROOT, path)
    if not is_safe_path(full_path):
        raise PermissionError(f"Access to path '{full_path}' is not allowed.")

    if not os.path.exists(full_path):
        raise FileNotFoundError(f"Path '{full_path}' does not exist.")
    if not os.path.isdir(full_path):
        raise NotADirectoryError(f"Path '{full_path}' is not a directory.")

    return os.listdir(full_path)


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
    log_action(f"moved '{src}' -> '{dst}'", target_path=dst)
    return f"Moved {src} to {dst}"


def create_folder(path):
    """Create a folder at the specified path relative to ALLOWED_ROOT."""
    full_path = os.path.join(ALLOWED_ROOT, path)

    if not is_safe_path(full_path):
        raise PermissionError(f"Path outside allowed workspace: {path}")

    os.makedirs(full_path, exist_ok=True)
    log_action(f"created folder '{path}'", target_path=path)
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

    log_action(f"organized {moved} files in '{folder}' by extension", target_path=folder)
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

    log_action(f"searched '{folder}' for empty files, found {len(empty)}", target_path=folder)
    return empty
