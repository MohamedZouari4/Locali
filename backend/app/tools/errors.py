"""The fixed error codes every tool reports, each with a plain message the model and the user can read.

A tool raises ToolError with one of these codes. The built-in errors the file tools already raise are
translated here too, so a failing tool call always comes back as one code from ERROR_CODES and never as a
stack trace. Add a code here before any tool uses it, and keep the messages free of internal detail.
"""

ERROR_CODES = {
    "not_available": "That tool isn't available here.",
    "invalid_arguments": "The tool was called with missing or unknown arguments.",
    "not_found": "That file or folder doesn't exist.",
    "not_a_folder": "That path is a file, not a folder.",
    "outside_boundary": "That path is outside the folders Locali may use.",
    "too_large": "That file is too large to read.",
    "unsupported_type": "Locali can't read that type of file.",
    "failed": "The tool failed unexpectedly.",
}


class ToolError(Exception):
    """A tool failure with one of the fixed codes; `message` defaults to the code's plain message."""

    def __init__(self, code, message=None):
        if code not in ERROR_CODES:
            raise ValueError(f"Unknown tool error code: {code}")
        self.code = code
        self.message = message or ERROR_CODES[code]
        super().__init__(self.message)


# Built-in errors the file tools raise, checked in order (NotADirectoryError is not a FileNotFoundError,
# but both are OSErrors, so the specific ones come first).
_BUILT_IN = (
    (PermissionError, "outside_boundary"),
    (FileNotFoundError, "not_found"),
    (NotADirectoryError, "not_a_folder"),
)


def from_exception(error):
    """The ToolError for anything a tool raised. An unexpected error becomes `failed` with the plain message,
    so internal detail never reaches the model."""
    if isinstance(error, ToolError):
        return error
    for kind, code in _BUILT_IN:
        if isinstance(error, kind):
            return ToolError(code, str(error) or None)
    return ToolError("failed")
