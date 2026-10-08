"""Indexed folders: the folders the user chose in the app for ingestion.

Each folder is checked before it is saved: it must be a full path to an existing folder, outside the
system, privacy and ignored folders, and not already covered by another indexed folder. Adding a
parent replaces the indexed folders inside it. Removing a folder queues a job that takes its files
out of the index, so they stop appearing in answers.
"""

import os

from app.ai.ingestion.walker import exclusion_reason, is_under
from app.db import database
from app.jobs import worker
from app.services import rag_service


class FolderRefused(ValueError):
    """A folder that can't be indexed; the message says why, in words for the user."""


def list_folders():
    return database.list_indexed_folders()

def check_folder(path):
    """Returns the folder's normalized path. Raises FolderRefused with the reason if it can't be indexed:
    not a full path, missing, or a system, privacy or ignored folder."""
    if not path or not os.path.isabs(path):
        raise FolderRefused("Choose a folder with a full path, such as D:\\Documents.")
    path = os.path.normpath(path)
    if not os.path.isdir(path):
        raise FolderRefused(f"{path} doesn't exist or isn't a folder.")
    reason = exclusion_reason(path)
    if reason:
        raise FolderRefused(f"{path} can't be indexed because {reason}.")
    return path

def add_folder(path):
    """Checks the folder and adds it to the list, replacing any indexed folders inside it."""
    path = check_folder(path)
    existing = database.list_indexed_folders()
    for folder in existing:
        if is_under(path, folder["path"]) and is_under(folder["path"], path):
            raise FolderRefused(f"{path} is already in the list.")
        if is_under(path, folder["path"]):
            raise FolderRefused(f"{path} is already indexed as part of {folder['path']}.")
    inside = [folder["id"] for folder in existing if is_under(folder["path"], path)]
    return database.add_indexed_folder(path, replaces=inside)


def remove_folder(folder_id):
    """Takes the folder off the list and queues a job removing its files from the index.

    Returns False if there is no such folder.
    """
    path = database.remove_indexed_folder(folder_id)
    if path is None:
        return False
    worker.submit(rag_service.FORGET_FOLDER_KIND, {"path": path})
    return True
