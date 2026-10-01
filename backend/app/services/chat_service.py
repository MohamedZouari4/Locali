"""Chat use cases shared by the REST and WebSocket routes: picking the conversation and
turning an orchestrator answer into the /chat response shape.
"""

from app.ai.chat.orchestrator import ask
from app.db import database


def resolve_conversation(conversation_id, message):
    # Reuses the client's conversation when it exists, otherwise starts a new one titled
    # after the first message.
    if conversation_id and database.conversation_exists(conversation_id):
        return conversation_id
    return database.create_conversation(title=message.strip()[:60] or None)


def get_answer(message, use_docs=False, project=None, conversation_id=None):
    conversation_id = resolve_conversation(conversation_id, message)
    answer, sources, _ = ask(message, use_docs=use_docs, project=project, conversation_id=conversation_id)
    return {"response": answer, "sources": sources, "conversation_id": conversation_id}
