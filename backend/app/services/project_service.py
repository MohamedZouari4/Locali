"""Projects: a name, instructions for the assistant, and the folders it may use, each with Read or Act permissions.
A folder passes the same checks as an indexed folder before it is added (folder_service.check_folder).
A project can add its own ignore patterns to the default ignore lists; the catalog applies them.
Deleting a project deletes its folder list, its file catalog and its conversations, never the files in
its folders. There is no per-project search index yet; when there is, deleting a project must clear it too.
"""

import re
import sqlite3

from app.ai.ingestion.walker import is_under
from app.db import database
from app.services import catalog_service, project_boundary
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


def general_project():
    """The project named General, created if missing. The CLI chats there, and so does the desktop until it
    has a project picker."""
    for project in database.list_projects():
        if project["name"].lower() == "general":
            return project
    try:
        return create_project("General")
    except ProjectNameTaken:  # another process created it just now
        return general_project()


class InvalidPattern(ValueError):
    """An ignore pattern that isn't a name or a path inside the project's folders."""


def clean_patterns(patterns):
    """Trims the ignore patterns, uses forward slashes and drops empty lines and duplicates.

    Raises InvalidPattern for a full path (C:/..., //server/...) or one that climbs out with "..": a
    pattern only ever hides files inside the project's folders.
    """
    cleaned = []
    for raw in patterns:
        pattern = raw.strip().replace("\\", "/")
        if not pattern:
            continue
        if re.match(r"^[A-Za-z]:", pattern) or pattern.startswith("//") or ".." in pattern.split("/"):
            raise InvalidPattern(f"{raw} isn't allowed. Use a name or a path inside the project's folders, such as *.log or drafts/.")
        if pattern not in cleaned:
            cleaned.append(pattern)
    return cleaned


def update_project(project_id, name=None, instructions=None, ignore_patterns=None):
    """Returns the updated project, or None if it doesn't exist. Raises ProjectNameTaken or InvalidPattern.

    Changed ignore patterns queue a catalog scan, so files they now hide leave the catalog and files they
    no longer hide come back.
    """
    if ignore_patterns is not None:
        ignore_patterns = clean_patterns(ignore_patterns)
    before = database.get_project(project_id)
    try:
        if not database.update_project(project_id, name, instructions, ignore_patterns):
            return None
    except sqlite3.IntegrityError:
        raise _name_taken(name) from None
    if ignore_patterns is not None and ignore_patterns != before["ignore_patterns"]:
        catalog_service.start_scan(project_id)
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
