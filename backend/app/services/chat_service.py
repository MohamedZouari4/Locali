"""Chat use cases shared by the REST and WebSocket routes. This is where conversations are saved:
the user message before the model runs, the reply afterwards, complete or not.

Every chat belongs to a project. A turn in a project that doesn't exist is refused, and a conversation
from another project is never continued: database.begin_turn starts a new one instead.

Each question is routed first (app/ai/chat/router.py), unless retrieved passages may answer it: a project
question or a multi-step task then gets a search of the project's files before the model answers.
"""

from app.ai.chat import router
from app.ai.chat.orchestrator import ask
from app.core.config import CHAT_HISTORY_MESSAGES
from app.db import database


class ProjectNotFound(Exception):
    """The chat names a project that doesn't exist; it may have just been deleted."""


def begin_turn(project_id, conversation_id, message):
    """Saves the user message and an empty reply in the project. Returns (conversation_id, reply_id)."""
    if database.get_project(project_id) is None:
        raise ProjectNotFound("This project no longer exists.")
    return database.begin_turn(conversation_id, message, project_id)


def history(project_id, conversation_id):
    """The conversation's latest messages for the model. Read before begin_turn saves the new question, so the
    question isn't sent twice; empty for a new chat or one that belongs to another project."""
    return database.get_history(conversation_id, project_id, CHAT_HISTORY_MESSAGES) if conversation_id else []


def route(message, use_docs):
    """The router's route for the message, or None with "Use my docs" on: retrieved passages then take the
    tools' place, so there is nothing to route."""
    return None if use_docs else router.classify(message)


def get_answer(message, *, project_id, use_docs=False, project=None, conversation_id=None):
    history_so_far = history(project_id, conversation_id)
    conversation_id, reply_id = begin_turn(project_id, conversation_id, message)
    try:
        answer, sources, used_tools = ask(
            message,
            use_docs=use_docs,
            project=project,
            project_id=project_id,
            history=history_so_far,
            route=route(message, use_docs),
        )
    except BaseException:
        database.finish_turn(reply_id, "", complete=False)
        raise
    database.finish_turn(reply_id, answer, sources)
    return {"response": answer, "sources": sources, "conversation_id": conversation_id, "used_tools": used_tools}
