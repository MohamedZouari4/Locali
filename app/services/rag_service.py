from app.AI.ingest import ingest_all, reset_index
from app.AI.retriever import retrieve


def run_ingestion(full_reset=False):
    if full_reset:
        reset_index()
    ingest_all()
    return {"status": "ingestion complete"}


def search(query, k=4, project=None):
    results = retrieve(query, k=k, project=project)
    return [{"chunk": chunk[:300], "source": source} for chunk, source in results]
