from requests import RequestException

from app.AI.retrieval.dense_retriever import dense_search
from app.AI.retrieval.sparse_retriever import bm25_search, resolve_source_matches


RRF_K = 60
POOL_MULTIPLIER = 25


def reciprocal_rank_fusion(vector_rank, bm25_rank, rrf_k=RRF_K):
    all_ids = set(vector_rank) | set(bm25_rank)
    fused = []
    for cid in all_ids:
        score = 0.0
        if cid in vector_rank:
            score += 1.0 / (rrf_k + vector_rank[cid])
        if cid in bm25_rank:
            score += 1.0 / (rrf_k + bm25_rank[cid])
        fused.append((cid, score))
    fused.sort(key=lambda x: x[1], reverse=True)
    return fused


def hybrid_search(query, k=4, project=None):
    matches = resolve_source_matches(query, project=project)
    pool_size = max(k * POOL_MULTIPLIER, 100)

    vector_rank = {}
    vector_lookup = {}
    try:
        vector_rank, vector_lookup = dense_search(query, pool_size, matches)
    except (RequestException, ConnectionError, OSError) as exc:
        print(
            f"Warning: vector retrieval unavailable ({exc}); "
            "falling back to BM25-only ranking."
        )

    bm25_ids, id_to_doc, id_to_source = bm25_search(query, pool_size, matches)
    bm25_rank = {cid: rank for rank, cid in enumerate(bm25_ids)}
    fused = reciprocal_rank_fusion(vector_rank, bm25_rank)

    results = []
    for cid, _ in fused[:k]:
        if cid in vector_lookup:
            results.append(vector_lookup[cid])
        else:
            results.append((id_to_doc[cid], id_to_source[cid]))
    return results
