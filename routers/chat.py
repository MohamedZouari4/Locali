from fastapi import APIRouter
from pydantic import BaseModel
from orchestrator import ask

router = APIRouter()

class ChatRequest(BaseModel):
    message: str
    use_docs: bool = False
    project: str | None = None

class ChatResponse(BaseModel):
    response: str
    sources: list[str]

@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    response, sources, _ = ask(request.message, use_docs=request.use_docs, project=request.project)
    return ChatResponse(response=response, sources=sources)
