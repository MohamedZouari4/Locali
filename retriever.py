import chromadb
from config import VECTOR_DIR
from ingest import embed


client = chromadb.PersistentClient(path=VECTOR_DIR)
collection = client.get_or_create_collection("documents")

_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "for", "to", "is", "are", "what",
    "which", "and", "or", "with", "used", "use", "uses", "project", "about",
}

_source_cache = None

def _all_sources(refresh=False):
    """Return the set of distinct source paths currently indexed, cached in memory."""
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

def _path_segments(source):
    """Lowercased directory names and filename stem for a source path, e.g.
    'D:/Contify/app/models/__init__.py' -> {'d:', 'contify', 'app', 'models', '__init__'}.
    Used for exact-segment keyword matching (see _match_sources_by_keyword).
    """
    segments = set()
    for seg in source.replace("\\", "/").split("/"):
        seg = seg.lower()
        if not seg:
            continue
        segments.add(seg)
        segments.add(seg.rsplit(".", 1)[0])
    return segments

def _match_sources_by_keyword(query):
    """Find indexed sources whose path has a segment (directory name or filename stem)
    exactly matching a keyword from the query -- e.g. a project name such as "contify".
    Matching whole path *segments* rather than arbitrary substrings means a generic query
    word (e.g. "models") won't accidentally match unrelated files whose name merely
    *contains* that word (an ML textbook PDF titled "...Diffusion Models...pdf") while
    still catching a project name regardless of how the user capitalized it.
    """
    tokens = query.replace("/", " ").replace("\\", " ").split()
    keywords = []
    for i, tok in enumerate(tokens):
        word = tok.strip(".,?!:;'\"").lower()
        if i == 0:
            continue  # sentence-initial capitalization doesn't imply a proper noun
        if len(word) >= 4 and word not in _STOPWORDS:
            keywords.append(word)
    if not keywords:
        return []
    return [s for s in _all_sources() if _path_segments(s) & set(keywords)]

def _query_restricted(query_vec, k, sources):
    """Query, optionally restricted to `sources`, batching the $in filter.
    Chroma's SQLite backend silently drops (rather than errors on) a `where`
    filter once the $in list gets large, so a single query with hundreds of
    sources quietly falls back to unfiltered results. Batching keeps each
    filter small and merges candidates from all batches by distance.
    """
    if not sources:
        res = collection.query(query_embeddings=[query_vec], n_results=k)
        return list(zip(res["documents"][0], [m["source"] for m in res["metadatas"][0]], res["distances"][0]))

    candidates = []
    batch_size = 100
    for i in range(0, len(sources), batch_size):
        batch = sources[i:i + batch_size]
        res = collection.query(query_embeddings=[query_vec], n_results=k, where={"source": {"$in": batch}})
        candidates.extend(zip(res["documents"][0], [m["source"] for m in res["metadatas"][0]], res["distances"][0]))
    candidates.sort(key=lambda c: c[2])
    return candidates[:k]

def retrieve(query, k=4, project=None):
    """Return the k most relevant (chunk_text, source_file) pairs for a query.

    If `project` is given, restrict search to sources whose path contains that substring.
    Otherwise, auto-detect a project/file keyword in the query and, if it matches any
    indexed source, restrict the search to those sources before ranking by similarity.
    """
    if project:
        matches = [s for s in _all_sources() if project.lower() in s.lower()]
    else:
        matches = _match_sources_by_keyword(query)

    query_vec = embed(query)
    results = _query_restricted(query_vec, k, matches)
    return [(doc, source) for doc, source, _ in results]

