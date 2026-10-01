"""The file tools offered to the chat model: their JSON schemas and the functions they call."""

from app.tools import file_tools


def _tool(name, description, properties, required=()):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": list(required)},
        },
    }


def _string(description):
    return {"type": "string", "description": description}


TOOLS_SCHEMA = [
    _tool(
        "list_files",
        "List files and folders inside a path within the user's allowed workspace.",
        {"path": _string("Path relative to the workspace root. Use '.' for the root itself.")},
    ),
    _tool(
        "move_file",
        "Move or rename a file within the user's allowed workspace.",
        {
            "src": _string("Current path of the file, relative to the workspace root."),
            "dst": _string("Destination path for the file, relative to the workspace root."),
        },
        required=("src", "dst"),
    ),
    _tool(
        "create_folder",
        "Create a new folder (including any missing parent folders) within the user's allowed workspace.",
        {"path": _string("Path of the folder to create, relative to the workspace root.")},
        required=("path",),
    ),
    _tool(
        "organize_by_extension",
        "Sort every file in a folder into subfolders named after their file extension (e.g. jpg, pdf, txt).",
        {"folder": _string("Path of the folder to organize, relative to the workspace root. Use '.' for the root itself.")},
    ),
    _tool(
        "find_empty_files",
        "Search a folder (and its subfolders) for zero-byte empty files within the user's allowed workspace.",
        {"folder": _string("Path to search, relative to the workspace root. Use '.' for the whole workspace.")},
    ),
]

AVAILABLE_TOOLS = {
    "list_files": file_tools.list_files,
    "move_file": file_tools.move_file,
    "create_folder": file_tools.create_folder,
    "organize_by_extension": file_tools.organize_by_extension,
    "find_empty_files": file_tools.find_empty_files,
}
