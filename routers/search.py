from fastapi import APIRouter
from retriever import retrieve

router = APIRouter()

@router.get("/search")
def search(q: str, k: int = 4, project: str | None = None):
    """Search the indexed documents for the k most relevant chunks to the query."""
    results = retrieve(q, k=k, project=project)
    return {
        "query": q,
        "results": [{"chunk": chunk[:300], "source": source} for chunk, source in results]
    }
