import asyncio
import re

from fastapi import APIRouter, WebSocket
from pydantic import BaseModel
from app.AI.orchestrator import ask
from app.services.auth import API_TOKEN
from app.services import chat_service

router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    use_docs: bool = False
    project: str | None = None

class ChatResponse(BaseModel):
    response: str
    sources: list[str]

@router.post("/chat")
def chat(req: ChatRequest):
    return chat_service.get_answer(req.message, use_docs=req.use_docs, project=req.project)


@router.websocket("/chat/stream")
async def chat_stream(websocket: WebSocket):
    authorization = websocket.headers.get("authorization", "")
    if authorization != f"Bearer {API_TOKEN}":
        await websocket.close(code=1008, reason="Invalid API token")
        return

    await websocket.accept()
    try:
        payload = await websocket.receive_json()
        message = payload["message"]
        is_greeting = bool(re.match(
            r"^(hi|hello|hey|good morning|good afternoon|good evening)([!,.? ]|$)",
            message.strip().lower(),
        ))
        answer, sources, _used_tools = await asyncio.to_thread(
            ask,
            message,
            use_docs=payload.get("use_docs", not is_greeting),
            project=payload.get("project"),
            conversation_id=payload.get("conversation_id"),
        )
        await websocket.send_json({"type": "token", "text": answer})
        await websocket.send_json({"type": "final", "sources": sources})
    except Exception as error:
        await websocket.send_json({"type": "error", "text": str(error)})
    finally:
        await websocket.close()
