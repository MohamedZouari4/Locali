from app.AI.retrieval.hybrid_retriever import hybrid_search
from app.AI.retrieval.reranker import rerank

RERANK_CANDIDATES = 20


def retrieve(query, k=4, project=None):
    candidates = hybrid_search(
        query,
        k=max(k, RERANK_CANDIDATES),
        project=project,
    )
    return rerank(query, candidates, top_n=k)
