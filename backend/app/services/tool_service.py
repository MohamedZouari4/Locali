"""Wraps the file tools for the API, turning their errors into a ToolServiceError that carries one of the
fixed tool error codes (app/tools/errors.py) and an HTTP status code. Blocked attempts are audit-logged.
"""

import logging

from app.tools import file_tools as tools
from app.tools.audit_log import log_action
from app.tools.errors import from_exception

log = logging.getLogger(__name__)

# The HTTP status for each tool error code; any other code is a server error.
_STATUS = {"outside_boundary": 403, "not_found": 404, "not_a_folder": 404, "invalid_arguments": 422}


class ToolServiceError(Exception):
    """A tool failure for the API: a fixed error code, its message and the HTTP status code."""

    def __init__(self, message, status_code, code):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


def _run(func, **kwargs):
    """Runs a tool function and turns any error into a ToolServiceError."""
    try:
        return func(**kwargs)
    except Exception as exc:
        error = from_exception(exc)
        if error.code == "outside_boundary":
            log_action(f"blocked {func.__name__}({kwargs}): {error.message}", success=False)
        elif error.code == "failed":
            log.exception("The tool %s failed", func.__name__)
        raise ToolServiceError(error.message, _STATUS.get(error.code, 500), error.code) from None


def move_file(src, dst):
    """Move a file from src to dst using the tools module."""
    return _run(tools.move_file, src=src, dst=dst)


def create_folder(path):
    """Create a folder at the specified path using the tools module."""
    return _run(tools.create_folder, path=path)


def organize_by_extension(folder="."):
    """Organize files in the specified directory by their extensions using the tools module."""
    return _run(tools.organize_by_extension, folder=folder)


def list_files(path="."):
    """List files in the specified directory using the tools module."""
    return _run(tools.list_files, path=path)


def find_empty_files(folder="."):
    """Find empty files in the specified directory using the tools module."""
    return _run(tools.find_empty_files, folder=folder)
