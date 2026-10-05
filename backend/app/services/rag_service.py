"""Ingestion and search use cases.

Ingestion runs as an `ingest` background job (app/jobs/worker.py): the HTTP request returns at once
with the job, progress is reported per file, and the job can be cancelled. Only one ingestion can be
queued or running at a time. When a run ends, the keyword-search caches are rebuilt so newly indexed
files are searchable straight away.

Importing this module registers the `ingest` job kind; app/api/main.py imports it through the routers.
"""

from app.ai.ingestion import ingest_all, prune_stale, reset_index
from app.ai.retrieval import retrieve
from app.ai.retrieval.sparse_retriever import invalidate_caches
from app.db import database
from app.jobs import worker

INGEST_KIND = "ingest"


def run_ingestion(full_reset=False, report=None):
    """Run ingestion in the calling thread and return its counts. `report` is passed to the pipeline."""
    try:
        if full_reset:
            reset_index()
        result = ingest_all(report=report)
        result["pruned"] = prune_stale(report=report)
        return result
    finally:
        invalidate_caches()


@worker.handler(INGEST_KIND, single_flight=True)
def run_ingest_job(params, ctx):
    def report(current, total, message):
        ctx.check_cancelled()
        ctx.progress(current, total, message)

    return run_ingestion(bool(params.get("full_reset")), report)


def start_ingestion(full_reset=False):
    """Queue an ingestion job and return it. Raises worker.JobAlreadyActive if one is queued or running."""
    return database.get_job(worker.submit(INGEST_KIND, {"full_reset": full_reset}))


def latest_ingestion():
    """The most recent ingestion job, or None if there has never been one."""
    jobs = database.list_jobs(limit=1, kind=INGEST_KIND)
    return jobs[0] if jobs else None


def search(query, k=4, project=None):
    results = retrieve(query, k=k, project=project)
    return [{"chunk": chunk[:300], "source": source} for chunk, source in results]
