from fastapi import APIRouter
from retriever import retrieve
from services import rag_service

router = APIRouter()

@router.get("/search")
def search(q: str, k: int = 4, project: str | None = None):
    return {"query": q, "results": rag_service.search(q, k=k, project=project)}
