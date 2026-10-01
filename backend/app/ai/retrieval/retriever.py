"""Main retrieval entry point: fetches a wide hybrid candidate pool, then reranks it down to the top `k` chunks."""

from app.ai.retrieval.hybrid_retriever import hybrid_search
from app.ai.retrieval.reranker import rerank
from app.core.config import RERANK_CANDIDATES


def retrieve(query, k=4, project=None):
    candidates = hybrid_search(
        query,
        k=max(k, RERANK_CANDIDATES),
        project=project,
    )
    return rerank(query, candidates, top_n=k)
