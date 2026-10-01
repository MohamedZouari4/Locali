"""Ingestion and search use cases.

Ingestion runs in one background thread at a time, so the HTTP request returns at once and the
client polls the status. When a run finishes, the keyword-search caches are rebuilt so newly
indexed files are searchable straight away.
"""

import threading
import time

from app.ai.ingestion import ingest_all, prune_stale, reset_index
from app.ai.retrieval import retrieve
from app.ai.retrieval.sparse_retriever import invalidate_caches

_lock = threading.Lock()
_status = {"state": "idle", "full_reset": False, "started_at": None, "finished_at": None, "result": None, "error": None}


def run_ingestion(full_reset=False):
    """Run ingestion in the calling thread and return its counts."""
    try:
        if full_reset:
            reset_index()
        result = ingest_all()
        result["pruned"] = prune_stale()
        return result
    finally:
        invalidate_caches()


def _background_run(full_reset):
    try:
        result = run_ingestion(full_reset)
        _status.update(state="done", result=result)
    except Exception as error:
        _status.update(state="failed", error=str(error))
    finally:
        _status["finished_at"] = time.time()
        _lock.release()


def start_ingestion(full_reset=False):
    """Start ingestion in the background. Returns False if a run is already in progress."""
    if not _lock.acquire(blocking=False):
        return False
    _status.update(state="running", full_reset=full_reset, started_at=time.time(), finished_at=None, result=None, error=None)
    threading.Thread(target=_background_run, args=(full_reset,), name="ingestion", daemon=True).start()
    return True


def ingestion_status():
    return dict(_status)


def search(query, k=4, project=None):
    results = retrieve(query, k=k, project=project)
    return [{"chunk": chunk[:300], "source": source} for chunk, source in results]
