"""Router: classifies a chat message as general chat, a project question, an action request or a multi-step
task, with one short call to the chat model (P1-E5-T3).

The answer has a fixed shape: a JSON object {"route": <one of ROUTES>}, enforced through Ollama's structured
output. Anything else the model returns (bad JSON, an unknown label) falls back to a project question, the
route that still works when unsure: it gets the project's tools and answers from the files. Only the
message is classified, not the conversation, so a bare follow-up ("and the second one?") lands on the fallback.

classify() is a plain function. Nothing in the chat flow calls it yet: it becomes the first node of the
agent graph, and a wrong route would change which tools a question gets, so it is wired in once its
accuracy is measured (tests/fixtures/router_eval.yaml).
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
    "You sort a user's message to a local file assistant into exactly one route.\n"
    "general_chat: greetings, thanks, writing or rewriting text, translation, maths, general knowledge, explanations. "
    "No files are needed.\n"
    "project_question: a question about the user's own files or folders that one lookup or one read answers: finding "
    "files by name, type, size or date, searching for words, reading a page, describing a file or an image.\n"
    "action_request: one change to files or folders: create, move, copy, rename, delete or organize.\n"
    "multi_step: needs two or more steps before the answer: several lookups, reading many files, comparing files, "
    "or finding files and then changing them.\n"
    'Answer only with JSON: {"route": "<route>"}. The message can be in any language.'
)

_FORMAT = {"type": "object", "properties": {"route": {"type": "string", "enum": list(ROUTES)}}, "required": ["route"]}


def parse_route(text):
    """The route named in the model's answer, or FALLBACK_ROUTE for anything that isn't a valid one."""
    try:
        route = json.loads(text).get("route")
    except (ValueError, AttributeError):  # not JSON, or JSON that isn't an object
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
