import chromadb

from app.AI.ingest import embed
from app.config import VECTOR_DIR


client = chromadb.PersistentClient(path=VECTOR_DIR)
collection = client.get_or_create_collection("documents")


def query_restricted(query_vec, k, sources):
    """Query Chroma, optionally restricted to a source list with batched $in filters."""
    if not sources:
        res = collection.query(query_embeddings=[query_vec], n_results=k)
        return list(
            zip(
                res["ids"][0],
                res["documents"][0],
                [m["source"] for m in res["metadatas"][0]],
                res["distances"][0],
            )
        )

    candidates = []
    batch_size = 100
    for i in range(0, len(sources), batch_size):
        batch = sources[i : i + batch_size]
        res = collection.query(
            query_embeddings=[query_vec],
            n_results=k,
            where={"source": {"$in": batch}},
        )
        candidates.extend(
            zip(
                res["ids"][0],
                res["documents"][0],
                [m["source"] for m in res["metadatas"][0]],
                res["distances"][0],
            )
        )
    candidates.sort(key=lambda c: c[3])
    return candidates[:k]


def dense_search(query, pool_size, sources):
    query_vec = embed(query)
    vector_results = query_restricted(query_vec, pool_size, sources)
    vector_rank = {cid: rank for rank, (cid, _, _, _) in enumerate(vector_results)}
    vector_lookup = {cid: (doc, source) for cid, doc, source, _ in vector_results}
    return vector_rank, vector_lookup
