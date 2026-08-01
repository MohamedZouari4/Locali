from fastapi import APIRouter
from pydantic import BaseModel
from orchestrator import ask
from services import chat_service

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
