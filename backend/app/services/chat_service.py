"""Chat use cases shared by the REST and WebSocket routes. This is where conversations are saved:
the user message before the model runs, the reply afterwards, complete or not.
"""

from app.ai.chat.orchestrator import ask
from app.db import database


def get_answer(message, use_docs=False, project=None, conversation_id=None):
    conversation_id, reply_id = database.begin_turn(conversation_id, message)
    try:
        answer, sources, used_tools = ask(message, use_docs=use_docs, project=project)
    except BaseException:
        database.finish_turn(reply_id, "", complete=False)
        raise
    database.finish_turn(reply_id, answer, sources)
    return {"response": answer, "sources": sources, "conversation_id": conversation_id, "used_tools": used_tools}
