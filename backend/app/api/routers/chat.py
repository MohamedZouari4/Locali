"""Chat endpoints: POST /chat returns a complete answer. The /chat/stream WebSocket checks the token
itself, then streams the answer as the events in app/chat_events.py: tokens, sources, then done.

Both continue the conversation named by `conversation_id`, or start a new one and return its id.
"""

import asyncio
import contextlib
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from starlette.concurrency import iterate_in_threadpool

from app.ai.chat.orchestrator import ask_stream
from app.chat_events import CHAT_SUBPROTOCOL, ChatStreamRequest, DoneEvent, ErrorEvent, SourcesEvent, TokenEvent
from app.core.security import is_valid_token
from app.db import database
from app.services import chat_service

router = APIRouter()

GREETING_RE = re.compile(r"^(hi|hello|hey|good morning|good afternoon|good evening)([!,.? ]|$)")


class ChatRequest(BaseModel):
    message: str
    use_docs: bool = False
    project: str | None = None
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    sources: list[str]
    conversation_id: str


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    return chat_service.get_answer(
        req.message,
        use_docs=req.use_docs,
        project=req.project,
        conversation_id=req.conversation_id,
    )


@router.websocket("/chat/stream")
async def chat_stream(websocket: WebSocket):
    authorization = websocket.headers.get("authorization", "")
    if not is_valid_token(authorization.removeprefix("Bearer ").strip()):
        await websocket.close(code=1008, reason="Invalid API token")
        return

    # Clients choose the event contract version through the WebSocket subprotocol (docs/CHAT_EVENTS.md).
    requested = websocket.scope.get("subprotocols", [])
    if requested and CHAT_SUBPROTOCOL not in requested:
        await websocket.close(code=1008, reason=f"Unsupported protocol, use {CHAT_SUBPROTOCOL}")
        return

    await websocket.accept(subprotocol=CHAT_SUBPROTOCOL if requested else None)
    events = None
    reply_id = None
    parts = []
    sources = None
    try:
        request = ChatStreamRequest.model_validate(await websocket.receive_json())
        is_greeting = bool(GREETING_RE.match(request.message.strip().lower()))
        use_docs = request.use_docs if request.use_docs is not None else not is_greeting
        # Save the user message (and an empty reply marked streaming) before the model runs.
        conversation_id, reply_id = await asyncio.to_thread(database.begin_turn, request.conversation_id, request.message)
        events = ask_stream(request.message, use_docs=use_docs, project=request.project)
        # Each next() on the generator runs in a worker thread so the server isn't blocked.
        async for event in iterate_in_threadpool(events):
            if isinstance(event, TokenEvent):
                parts.append(event.text)
            elif isinstance(event, SourcesEvent):
                sources = event.sources
            await websocket.send_json(event.model_dump())
        # Saved before done is sent, so a client that sees done can rely on the reply being stored.
        await asyncio.to_thread(database.finish_turn, reply_id, "".join(parts), sources)
        await websocket.send_json(DoneEvent(conversation_id=conversation_id).model_dump())
    except WebSocketDisconnect:
        pass  # The client left mid-answer; cleanup happens below.
    except Exception as error:
        # The socket may already be closed, so sending the error can fail too.
        with contextlib.suppress(Exception):
            await websocket.send_json(ErrorEvent(text=str(error)).model_dump())
    finally:
        if events is not None:
            events.close()  # Stops the generator and closes the Ollama request.
        if reply_id is not None:
            # Stores whatever arrived as incomplete; does nothing if the reply was already saved complete.
            # Called directly rather than in a thread so it still runs if the server is shutting down.
            database.finish_turn(reply_id, "".join(parts), sources, complete=False)
        with contextlib.suppress(Exception):
            await websocket.close()
