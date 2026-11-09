"""Router: classifies a chat message as general chat, a project question, an action request or a multi-step
task, with one short call to the chat model (P1-E5-T3).

The answer has a fixed shape: a JSON object {"route": <one of ROUTES>}, enforced through Ollama's structured
output. Anything else the model returns (bad JSON, an unknown label) falls back to a project question, the
route that still works when unsure: it gets the project's tools and answers from the files. Only the
message is classified, not the conversation, so a bare follow-up ("and the second one?") lands on the fallback.

classify() is a plain function, called by chat_service.route before each project chat turn. The route decides
one thing today: a project question or a multi-step task gets a search of the project's files before the model
answers (orchestrator.py), because a small model otherwise answers from memory. The prompt asks for the
decision in a fixed order, because the model kept labelling "each", "every" and "then" requests as single
questions; its accuracy is measured on tests/fixtures/router_eval.yaml.
"""

import json

import requests

from app.core.config import CHAT_MODEL, OLLAMA_URL

ROUTES = ("general_chat", "project_question", "action_request", "multi_step")
FALLBACK_ROUTE = "project_question"
# A very long message is cut before it is classified, so the call stays fast.
MAX_MESSAGE_CHARS = 2000
TIMEOUT_SECONDS = 30

ROUTER_PROMPT = (
    "You sort a user's message to a local file assistant into exactly one route. Decide in this order.\n"
    "1. general_chat: no files are needed: greetings, thanks, writing or rewriting text the user gives, translation, "
    "maths, general knowledge, explanations. A question about the user's own project, reports, notes, meetings, "
    "people, budget, code or data needs their files, even when it doesn't say 'file'.\n"
    "2. multi_step: the request has two or more parts or covers many files: it says each, every, all, then, and then, "
    "compare, go through, list every, or finds files and then reads, summarizes, moves or deletes them.\n"
    "3. action_request: one change to named files or folders: create, move, copy, rename, delete or organize.\n"
    "4. project_question: anything else about the user's files: one fact, one search, one file or one page.\n"
    'Answer only with JSON: {"route": "<route>"}. The message can be in any language.'
)

_FORMAT = {"type": "object", "properties": {"route": {"type": "string", "enum": list(ROUTES)}}, "required": ["route"]}


def parse_route(text):
    """The route named in the model's answer, or FALLBACK_ROUTE for anything that isn't a valid one."""
    try:
        route = json.loads(text).get("route")
    except (ValueError, AttributeError, TypeError):  # not JSON, JSON that isn't an object, or not text at all
        return FALLBACK_ROUTE
    return route if route in ROUTES else FALLBACK_ROUTE


def classify(message):
    """The route for one message. Raises if Ollama can't be reached; a bad answer is the fallback route."""
    response = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": CHAT_MODEL,
            "messages": [
                {"role": "system", "content": ROUTER_PROMPT},
                {"role": "user", "content": message[:MAX_MESSAGE_CHARS]},
            ],
            "stream": False,
            "format": _FORMAT,
            "options": {"temperature": 0, "num_predict": 30},
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return parse_route(response.json()["message"]["content"])
