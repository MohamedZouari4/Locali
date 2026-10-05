"""The ChromaDB "documents" collection: one shared client for ingestion and retrieval, plus
helpers that redact, embed and write chunks, replace a file's chunks, search, and reset.
"""

import chromadb

from app.ai.ingestion.embeddings import embed, embed_batch
from app.ai.ingestion.redaction import classify_sensitivity, redact_pii
from app.core import config

COLLECTION_NAME = "documents"
WRITE_BATCH_SIZE = 500
DELETE_BATCH_SIZE = 5000  # below Chroma's maximum batch size for SQLite-backed stores
# Reading a large index in one call makes Chroma build an SQL query with more variables than
# SQLite allows ("too many SQL variables"), so whole-index reads go in pages of this size.
READ_BATCH_SIZE = 1000

_collection = None


def get_collection():
    """Return the shared collection, opening it on first use at the configured VECTOR_DIR."""
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=config.VECTOR_DIR)
        _collection = client.get_or_create_collection(COLLECTION_NAME)
    return _collection


def close_collection():
    """Forget the open collection so the next call reopens it (used when VECTOR_DIR changes in tests)."""
    global _collection
    _collection = None


def store_chunks(chunks, mtime, content_hash):
    """Redact, embed, and persist chunks with their metadata envelope."""
    collection = get_collection()
    for start in range(0, len(chunks), WRITE_BATCH_SIZE):
        batch = chunks[start : start + WRITE_BATCH_SIZE]
        redacted_texts = []
        for chunk in batch:
            redacted_text, hits = redact_pii(chunk["text"])
            chunk["sensitivity"] = classify_sensitivity(hits)
            redacted_texts.append(redacted_text)
        vectors = embed_batch(redacted_texts)
        collection.add(
            ids=[chunk["chunk_id"] for chunk in batch],
            documents=redacted_texts,
            embeddings=vectors,
            metadatas=[
                {
                    "document_id": chunk["document_id"],
                    "section": chunk["section"],
                    "heading_path": chunk["heading_path"],
                    "chunk_index": chunk["chunk_index"],
                    "total_chunks": chunk["total_chunks"],
                    "source": chunk["source"],
                    "file_type": chunk["file_type"],
                    "source_type": chunk["source_type"],
                    "language": chunk["language"],
                    "sensitivity": chunk["sensitivity"],
                    "token_count": chunk["token_count"],
                    "mtime": mtime,
                    "file_hash": content_hash,
                }
                for chunk in batch
            ],
        )


def replace_source_chunks(source, chunks, mtime, content_hash):
    """Replace a source and restore its previous records if indexing fails."""
    collection = get_collection()
    existing = collection.get(where={"source": source}, include=["documents", "metadatas", "embeddings"])
    backup = {key: existing.get(key, []) for key in ("ids", "documents", "metadatas", "embeddings")}
    try:
        collection.delete(where={"source": source})
        store_chunks(chunks, mtime, content_hash)
    except Exception:
        collection.delete(where={"source": source})
        if backup["ids"]:
            collection.add(
                ids=backup["ids"],
                documents=backup["documents"],
                embeddings=backup["embeddings"],
                metadatas=backup["metadatas"],
            )
        raise


def stored_hash(source):
    """Return the file hash recorded for a source, or None if it is not indexed."""
    existing = get_collection().get(where={"source": source}, limit=1, include=["metadatas"])
    return existing["metadatas"][0].get("file_hash") if existing["metadatas"] else None


def _read_all(include):
    """Yield every record of the index in pages of READ_BATCH_SIZE, as Chroma `get` results."""
    collection = get_collection()
    total = collection.count()
    for offset in range(0, total, READ_BATCH_SIZE):
        yield collection.get(limit=READ_BATCH_SIZE, offset=offset, include=include)


def indexed_sources():
    """Return the distinct source paths currently in the index."""
    return {meta["source"] for page in _read_all(["metadatas"]) for meta in page["metadatas"]}


def delete_source(source):
    get_collection().delete(where={"source": source})


def reset_index():
    """Delete every chunk from the index.

    Deletes by id, because Chroma rejects an empty `where={}` filter.
    """
    collection = get_collection()
    # Collect every id before deleting, so deletions don't shift the pages still being read.
    ids = [chunk_id for page in _read_all([]) for chunk_id in page["ids"]]
    for start in range(0, len(ids), DELETE_BATCH_SIZE):
        collection.delete(ids=ids[start : start + DELETE_BATCH_SIZE])
    print(f"Index reset complete ({len(ids)} chunks removed).")
    return len(ids)


def search(query_text, n_results=5, source_type=None, file_type=None, sensitivity=None):
    """Search the index with optional metadata filters."""
    conditions = []
    for key, value in (
        ("source_type", source_type),
        ("file_type", file_type),
        ("sensitivity", sensitivity),
    ):
        if value:
            conditions.append({key: value})
    where = {"$and": conditions} if len(conditions) > 1 else (conditions[0] if conditions else None)
    return get_collection().query(query_embeddings=[embed(query_text)], n_results=n_results, where=where)
