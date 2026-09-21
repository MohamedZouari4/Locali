import re

import chromadb
from rank_bm25 import BM25Okapi

from app.config import VECTOR_DIR


client = chromadb.PersistentClient(path=VECTOR_DIR)
collection = client.get_or_create_collection("documents")

_STOPWORDS = {
    "the",
    "a",
    "an",
    "of",
    "in",
    "on",
    "for",
    "to",
    "is",
    "are",
    "what",
    "which",
    "and",
    "or",
    "with",
    "used",
    "use",
    "uses",
    "project",
    "about",
}

_source_cache = None
_bm25_cache = None


def all_sources(refresh=False):
    """Return distinct source paths currently indexed, cached in memory."""
    global _source_cache
    if _source_cache is not None and not refresh:
        return _source_cache
    sources = set()
    total = collection.count()
    for offset in range(0, total, 1000):
        batch = collection.get(limit=1000, offset=offset, include=["metadatas"])
        sources.update(m["source"] for m in batch["metadatas"])
    _source_cache = sources
    return sources


def tokenize(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def build_bm25_index(refresh=False):
    global _bm25_cache
    if _bm25_cache is not None and not refresh:
        return _bm25_cache

    ids, docs, sources = [], [], []
    total = collection.count()
    for offset in range(0, total, 1000):
        batch = collection.get(
            limit=1000,
            offset=offset,
            include=["documents", "metadatas"],
        )
        ids.extend(batch["ids"])
        docs.extend(batch["documents"])
        sources.extend(m["source"] for m in batch["metadatas"])

    tokenized_docs = [tokenize(doc) for doc in docs]
    bm25 = BM25Okapi(tokenized_docs)
    id_to_doc = dict(zip(ids, docs))
    id_to_source = dict(zip(ids, sources))

    _bm25_cache = (bm25, ids, id_to_doc, id_to_source)
    return _bm25_cache


def bm25_search(query, pool_size, sources=None):
    bm25, ids, id_to_doc, id_to_source = build_bm25_index()
    scores = bm25.get_scores(tokenize(query))
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

    if sources:
        allowed_sources = set(sources)
        ranked_ids = [
            ids[i] for i in ranked if id_to_source[ids[i]] in allowed_sources
        ][:pool_size]
    else:
        ranked_ids = [ids[i] for i in ranked[:pool_size]]

    return ranked_ids, id_to_doc, id_to_source


def path_segments(source):
    segments = set()
    for seg in source.replace("\\", "/").split("/"):
        seg = seg.lower()
        if not seg:
            continue
        segments.add(seg)
        segments.add(seg.rsplit(".", 1)[0])
    return segments


def match_sources_by_keyword(query):
    tokens = query.replace("/", " ").replace("\\", " ").split()
    keywords = []
    for i, tok in enumerate(tokens):
        word = tok.strip(".,?!:;'\"").lower()
        if i == 0:
            continue
        if len(word) >= 4 and word not in _STOPWORDS:
            keywords.append(word)
    if not keywords:
        return []
    keyword_set = set(keywords)
    return [s for s in all_sources() if path_segments(s) & keyword_set]


def resolve_source_matches(query, project=None):
    if project:
        return [s for s in all_sources() if project.lower() in s.lower()]
    return match_sources_by_keyword(query)
