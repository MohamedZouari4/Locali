"""Chat use cases shared by the REST and WebSocket routes. This is where conversations are saved:
the user message before the model runs, the reply afterwards, complete or not.

Every chat belongs to a project. A turn in a project that doesn't exist is refused, and a conversation
from another project is never continued: database.begin_turn starts a new one instead.
"""

from app.ai.chat.orchestrator import ask
from app.db import database


class ProjectNotFound(Exception):
    """The chat names a project that doesn't exist; it may have just been deleted."""


def begin_turn(project_id, conversation_id, message):
    """Saves the user message and an empty reply in the project. Returns (conversation_id, reply_id)."""
    if database.get_project(project_id) is None:
        raise ProjectNotFound("This project no longer exists.")
    return database.begin_turn(conversation_id, message, project_id)


def get_answer(message, *, project_id, use_docs=False, project=None, conversation_id=None):
    conversation_id, reply_id = begin_turn(project_id, conversation_id, message)
    try:
        answer, sources, used_tools = ask(message, use_docs=use_docs, project=project, project_id=project_id)
    except BaseException:
        database.finish_turn(reply_id, "", complete=False)
        raise
    database.finish_turn(reply_id, answer, sources)
    return {"response": answer, "sources": sources, "conversation_id": conversation_id, "used_tools": used_tools}
