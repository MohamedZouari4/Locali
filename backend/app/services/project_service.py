"""Projects: a name, instructions for the assistant, and the folders it may use, each with Read or Act.

A folder passes the same checks as an indexed folder before it is added (folder_service.check_folder).
Deleting a project deletes its folder list and its conversations, never the files in its folders.
There is no per-project index or cache yet; when there is, deleting a project must clear it here too.
"""

import sqlite3

from app.ai.ingestion.walker import is_under
from app.db import database
from app.services import project_boundary
from app.services.folder_service import FolderRefused, check_folder


class ProjectNameTaken(ValueError):
    """Another project already has this name (names are compared ignoring case)."""


def _name_taken(name):
    return ProjectNameTaken(f"A project named {name} already exists.")


def create_project(name, instructions=""):
    try:
        return database.create_project(name, instructions)
    except sqlite3.IntegrityError:  # the only constraint a new project without folders can break is the unique name
        raise _name_taken(name) from None


def update_project(project_id, name=None, instructions=None):
    """Returns the updated project, or None if it doesn't exist. Raises ProjectNameTaken."""
    try:
        if not database.update_project(project_id, name, instructions):
            return None
    except sqlite3.IntegrityError:
        raise _name_taken(name) from None
    return database.get_project(project_id)


def add_folder(project_id, path, permission):
    """Checks and adds a folder, and returns it, or None if the project doesn't exist.

    Raises FolderRefused with the reason if the folder can't be used or is already in the project.
    """
    project = database.get_project(project_id)
    if project is None:
        return None
    path = check_folder(path)
    for folder in project["folders"]:
        if is_under(path, folder["path"]) and is_under(folder["path"], path):
            raise FolderRefused(f"{path} is already in this project.")
    return database.add_project_folder(project_id, path, permission)


def check_path(project_id, path):
    """Returns (resolved path, folder) when the path is inside one of the project's folders; the folder
    carries its permission ("read" or "act"). Returns None if the project doesn't exist.

    Raises project_boundary.PathRefused with the reason otherwise.
    """
    project = database.get_project(project_id)
    if project is None:
        return None
    return project_boundary.check_path(path, project["folders"])
