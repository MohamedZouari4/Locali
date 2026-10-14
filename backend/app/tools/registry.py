"""The tool registry: which tools the chat model may use, what it is offered each step, and how a call runs.

Only a tool with a valid card (cards.py) whose parameters match its function is loaded; any other tool in
FUNCTIONS is refused and logged, so removing a card makes its tool unavailable. Each step offers at most
MAX_TOOLS_PER_STEP tools, the lowest risk first, and a call runs only if its tool was offered in that step,
so a tool that was withheld (for example while file contents are in the prompt) can never run.

A call's result is {"ok": True, "result": ...} or {"ok": False, "error": {"code", "message"}}, with a code
from errors.ERROR_CODES. Calls blocked at the boundary are written to the audit log.
"""

import inspect
import logging

from app.tools import file_tools
from app.tools.audit_log import log_action
from app.tools.cards import CARDS, RISK_LEVELS, check
from app.tools.errors import ToolError, from_exception

log = logging.getLogger(__name__)

# Every tool the model could be given, by name. A tool listed here still needs a card to load.
FUNCTIONS = {
    "list_files": file_tools.list_files,
    "find_empty_files": file_tools.find_empty_files,
    "create_folder": file_tools.create_folder,
    "move_file": file_tools.move_file,
    "organize_by_extension": file_tools.organize_by_extension,
}


def load(cards, functions):
    """{name: (card, function)} for each function with a valid card; any other function is refused and logged.
    A card for a function that doesn't exist is a mistake in the code, so it raises."""
    cards_by_name = {card.name: card for card in cards}
    unknown = set(cards_by_name) - set(functions)
    if unknown:
        raise ValueError(f"Cards without a tool: {', '.join(sorted(unknown))}")
    tools = {}
    for name, function in functions.items():
        card = cards_by_name.get(name)
        if card is None:
            log.warning("Refused to load the tool %s: it has no card.", name)
            continue
        try:
            check(card)
            _check_parameters(card, function)
        except ValueError as error:
            log.warning("Refused to load the tool %s: %s", name, error)
            continue
        tools[name] = (card, function)
    return tools


def _check_parameters(card, function):
    # The card is what the model sees, so it must describe exactly the parameters the function takes.
    parameters = set(inspect.signature(function).parameters)
    if parameters != set(card.parameters):
        raise ValueError(f"its parameters {sorted(card.parameters)} don't match the function's {sorted(parameters)}")


TOOLS = load(CARDS, FUNCTIONS)


def offer(limit):
    """The cards of at most `limit` tools to offer in one step: the lowest risk first, then in card order."""
    cards = [card for card, _ in TOOLS.values()]
    return sorted(cards, key=lambda card: RISK_LEVELS.index(card.risk))[:limit]


def schema(card):
    """The card as a function schema for the chat model."""
    return {
        "type": "function",
        "function": {
            "name": card.name,
            "description": card.purpose,
            "parameters": {"type": "object", "properties": card.parameters, "required": list(card.required)},
        },
    }


def run(name, arguments, offered):
    """Runs one tool call from the model, if `name` was among the `offered` tool names this step."""
    try:
        tool = TOOLS.get(name)
        if tool is None or name not in offered:
            raise ToolError("not_available", f"There is no tool called {name} here.")
        card, function = tool
        if not isinstance(arguments, dict) or set(arguments) - set(card.parameters) or set(card.required) - set(arguments):
            raise ToolError("invalid_arguments", f"{name} takes {', '.join(card.parameters) or 'no arguments'}.")
        return {"ok": True, "result": function(**arguments)}
    except Exception as exc:
        error = from_exception(exc)
        if error.code == "outside_boundary":
            log_action(f"blocked {name}({arguments}): {error.message}", success=False)
        elif error.code == "failed":
            log.exception("The tool %s failed", name)
        return {"ok": False, "error": {"code": error.code, "message": error.message}}
