"""Chat endpoints: POST /chat returns a complete answer. The /chat/stream WebSocket checks the token
itself, then streams the answer token by token and ends with a final event carrying the sources.

Both continue the conversation named by `conversation_id`, or start a new one and return its id.
"""

import asyncio
import contextlib
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from starlette.concurrency import iterate_in_threadpool

from app.ai.chat.orchestrator import ask_stream
from app.core.security import is_valid_token
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

    await websocket.accept()
    events = None
    try:
        payload = await websocket.receive_json()
        message = payload["message"]
        is_greeting = bool(GREETING_RE.match(message.strip().lower()))
        conversation_id = await asyncio.to_thread(chat_service.resolve_conversation, payload.get("conversation_id"), message)
        events = ask_stream(
            message,
            use_docs=payload.get("use_docs", not is_greeting),
            project=payload.get("project"),
            conversation_id=conversation_id,
        )
        # Each next() on the generator runs in a worker thread so the server isn't blocked.
        async for event in iterate_in_threadpool(events):
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass  # The client left mid-answer; cleanup happens below.
    except Exception as error:
        # The socket may already be closed, so sending the error can fail too.
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "text": str(error)})
    finally:
        if events is not None:
            events.close()  # Stops the generator and closes the Ollama request.
        with contextlib.suppress(Exception):
            await websocket.close()
