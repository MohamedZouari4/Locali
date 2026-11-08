"""Read-only tools that summarize or search a project's catalog without accessing the filesystem directly.

Each takes the chat's project_id from the registry, never from the model. find_files turns the model's
arguments (strings, numbers in megabytes, a named period) into catalog filters, and refuses anything it can't
read as invalid_arguments, so the model is told what to fix instead of getting a wrong answer.
"""

import re
from datetime import UTC, datetime

from app.services import catalog_service
from app.tools.errors import ToolError

_MB = 1024 * 1024


def project_overview(project_id):
    """Summarize the structure, file types and recent catalog changes of one project."""
    overview = catalog_service.project_overview(project_id)
    if overview is None:
        raise ToolError("not_found", "This project no longer exists.")
    return overview


def find_files(project_id, name=None, extension=None, larger_than_mb=None, smaller_than_mb=None, changed=None):
    """The project's catalogued files that match every filter given, most recently changed first."""
    if changed is not None and changed not in catalog_service.CHANGED_PERIODS:
        raise ToolError("invalid_arguments", f"changed must be one of: {', '.join(catalog_service.CHANGED_PERIODS)}.")
    found = catalog_service.find_files(
        project_id,
        name=name.strip() if isinstance(name, str) and name.strip() else None,
        extensions=_extensions(extension),
        min_size=_bytes(larger_than_mb, "larger_than_mb"),
        max_size=_bytes(smaller_than_mb, "smaller_than_mb"),
        changed=changed,
    )
    if found is None:
        raise ToolError("not_found", "This project no longer exists.")
    files = [
        {"id": row["id"], "path": row["path"], "size": _size(row["size"]), "modified": _local_date(row["file_modified_at"])}
        for row in found["files"]
    ]
    result = {"total": found["total"], "shown": len(files), "files": files}
    if found["total"] > len(files):
        result["note"] = f"{found['total'] - len(files)} more match; narrow the search to see them."
    return result


def _extensions(value):
    # "PDF", ".pdf" and "docx, xlsx" all work; the catalog stores extensions in lower case without the dot.
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolError("invalid_arguments", "extension must be text, such as pdf or docx, xlsx.")
    extensions = {part.lstrip(".").lower() for part in re.split(r"[\s,;]+", value) if part.strip(". ")}
    return extensions or None


def _bytes(megabytes, argument):
    # The model sends megabytes, sometimes as a string; the catalog stores bytes.
    if megabytes is None:
        return None
    try:
        value = float(megabytes)
    except (TypeError, ValueError):
        raise ToolError("invalid_arguments", f"{argument} must be a number of megabytes.") from None
    if value < 0:
        raise ToolError("invalid_arguments", f"{argument} can't be negative.")
    return int(value * _MB)


def _size(size):
    if size < 1024:
        return f"{size} bytes"
    if size < _MB:
        return f"{size / 1024:.1f} KB"
    return f"{size / _MB:.1f} MB"


def _local_date(timestamp):
    # The catalog stores UTC; the user thinks in their own day.
    return datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).astimezone().strftime("%Y-%m-%d")
