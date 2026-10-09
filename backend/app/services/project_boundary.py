"""Project boundary: decides whether a path is inside one of a project's folders.

The path and the folders are fully resolved before they are compared: ".." segments, symbolic links,
Windows junctions and short (8.3) names, and letter case on Windows. A link inside a folder is judged
by where it leads, so one pointing outside is refused. Folders are compared whole, so D:\\Thesis does
not contain D:\\Thesis-old. A path that doesn't exist yet is resolved as far as it exists, so the
target of a new file can be checked too.
"""

import os
import re

from app.ai.ingestion.walker import is_under

# Windows opens these as devices (the console, printer, serial ports...) wherever they appear in a
# path, with or without an extension, so they would leave the folder without looking like it.
_DEVICE_NAME = re.compile(r"(CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[0-9¹²³]|LPT[0-9¹²³])(\..*)?", re.IGNORECASE)


class PathRefused(PermissionError):
    """A path the project may not use; the message says why, in words for the user."""


def _device_name(path):
    if os.name != "nt":
        return None
    for part in os.path.normpath(path).split(os.sep):
        if _DEVICE_NAME.fullmatch(part.rstrip(". ")):
            return part
    return None


def _resolve(path):
    try:
        return os.path.realpath(path)
    except (OSError, ValueError) as error:  # rare without strict=True; refuse rather than guess
        raise PathRefused(f"{path!r} can't be checked ({error}).") from None


def check_path(path, folders):
    """Returns (resolved path, folder) for the folder that contains the path, the innermost one if
    folders are nested. `folders` are a project's folders, dicts with a "path" key.

    Raises PathRefused with the reason if the path is empty, not a full path, uses a Windows device name,
    or is outside every folder (including through a link).
    """
    if not path:
        raise PathRefused("No path was given.")
    if "\0" in path:
        raise PathRefused("The path contains a null character.")
    if not os.path.isabs(path):
        raise PathRefused(f"{path} isn't a full path, such as D:\\Thesis\\notes.txt.")
    if device := _device_name(path):
        raise PathRefused(f"{path} uses {device}, a name Windows reserves for a device.")
    if not folders:
        raise PathRefused("This project has no folders yet.")

    resolved = _resolve(path)
    containing = []
    for folder in folders:
        root = _resolve(folder["path"])
        if is_under(resolved, root):
            containing.append((len(root), folder))
    if containing:
        _, folder = max(containing, key=lambda pair: pair[0])
        return resolved, folder

    # Inside a folder as written but not once resolved: a link (or junction) leads out of it.
    if any(is_under(path, folder["path"]) for folder in folders):
        raise PathRefused(f"{path} leads outside this project's folders, to {resolved}.")
    raise PathRefused(f"{path} is outside this project's folders.")
