"""Description cards for the chat model's tools: what each tool is for, its parameters and output, its risk
level, the space it works in, how it is undone, and whether it uses the network (Architecture §11.2, ADR-024).

A tool runs only with a card here (see registry.py). The risk levels are the Architecture's:
L0 read only, L1 safe write, L2 reversible change, L3 destructive or leaves the device, L4 system.
A card at L1 or above must say how the change is undone ("Irreversible" if it can't be).
"""

from dataclasses import dataclass, field

RISK_LEVELS = ("L0", "L1", "L2", "L3", "L4")
# Where a tool works. "workspace" is the ALLOWED_ROOT folder the file tools use until they move onto
# project folders; "project" is a project's own folders.
SPACES = ("workspace", "project")
# Read: the tool may see the space. Act: it may change it (Architecture §11.1).
ACCESS = ("read", "act")


@dataclass(frozen=True)
class ToolCard:
    name: str
    purpose: str  # what the model is told the tool does
    parameters: dict  # parameter name -> JSON schema, e.g. {"path": {"type": "string", "description": ...}}
    output: dict  # JSON schema of a successful result
    risk: str  # one of RISK_LEVELS
    space: str  # one of SPACES
    access: str  # one of ACCESS
    undo: str | None = None  # how the change is undone; None for a read-only tool
    network: bool = False  # whether the tool uses the network
    required: tuple = field(default=())  # parameters the model must always give


def check(card):
    """Raises ValueError if the card is incomplete or contradicts itself."""
    problems = []
    if not card.purpose.strip():
        problems.append("it has no purpose")
    if card.risk not in RISK_LEVELS:
        problems.append(f"risk {card.risk!r} isn't one of {', '.join(RISK_LEVELS)}")
    if card.space not in SPACES:
        problems.append(f"space {card.space!r} isn't one of {', '.join(SPACES)}")
    if card.access not in ACCESS:
        problems.append(f"access {card.access!r} isn't read or act")
    if card.risk == "L0" and (card.access != "read" or card.undo is not None):
        problems.append("a read-only (L0) tool reads its space and has nothing to undo")
    if card.risk != "L0" and (card.access != "act" or not card.undo):
        problems.append("a tool that changes something acts on its space and says how it is undone")
    if set(card.required) - set(card.parameters):
        problems.append("it requires parameters it doesn't declare")
    if "type" not in card.output:
        problems.append("it declares no output shape")
    if problems:
        raise ValueError(f"The card for {card.name} is invalid: {'; '.join(problems)}.")


def _string(description):
    return {"type": "string", "description": description}


_MESSAGE = {"type": "string", "description": "A sentence saying what was done."}

CARDS = [
    ToolCard(
        name="list_files",
        purpose="List files and folders inside a path within the user's allowed workspace.",
        parameters={"path": _string("Path relative to the workspace root. Use '.' for the root itself.")},
        output={"type": "array", "items": {"type": "string"}, "description": "Names of the files and folders in the path."},
        risk="L0",
        space="workspace",
        access="read",
    ),
    ToolCard(
        name="find_empty_files",
        purpose="Search a folder (and its subfolders) for zero-byte empty files within the user's allowed workspace.",
        parameters={"folder": _string("Path to search, relative to the workspace root. Use '.' for the whole workspace.")},
        output={"type": "array", "items": {"type": "string"}, "description": "Paths of the empty files, relative to the workspace root."},
        risk="L0",
        space="workspace",
        access="read",
    ),
    ToolCard(
        name="create_folder",
        purpose="Create a new folder (including any missing parent folders) within the user's allowed workspace.",
        parameters={"path": _string("Path of the folder to create, relative to the workspace root.")},
        required=("path",),
        output=_MESSAGE,
        risk="L1",
        space="workspace",
        access="act",
        undo="Remove the folder if it is still empty.",
    ),
    ToolCard(
        name="move_file",
        purpose="Move or rename a file within the user's allowed workspace.",
        parameters={
            "src": _string("Current path of the file, relative to the workspace root."),
            "dst": _string("Destination path for the file, relative to the workspace root."),
        },
        required=("src", "dst"),
        output=_MESSAGE,
        risk="L2",
        space="workspace",
        access="act",
        undo="Move the file back.",
    ),
    ToolCard(
        name="organize_by_extension",
        purpose="Sort every file in a folder into subfolders named after their file extension (e.g. jpg, pdf, txt).",
        parameters={"folder": _string("Path of the folder to organize, relative to the workspace root. Use '.' for the root itself.")},
        output=_MESSAGE,
        risk="L2",
        space="workspace",
        access="act",
        undo="Move each file back to the folder.",
    ),
]
