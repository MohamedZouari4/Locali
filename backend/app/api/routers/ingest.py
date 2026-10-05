"""Ingestion endpoints. POST /ingest queues an `ingest` background job (optionally clearing the index
first with `full_reset=true`) and returns it at once with 202, or 409 if one is already queued or
running. Follow it with GET /jobs/{id} or the /jobs/events WebSocket. GET /ingest/status returns the
most recent ingestion job.
"""

from fastapi import APIRouter, HTTPException

from app.job_events import Job
from app.jobs import worker
from app.services import rag_service

router = APIRouter()


@router.post("/ingest", status_code=202, response_model=Job)
def trigger_ingest(full_reset: bool = False):
    try:
        return rag_service.start_ingestion(full_reset=full_reset)
    except worker.JobAlreadyActive:
        raise HTTPException(
            status_code=409, detail="Indexing is already running. Wait for it to finish, or cancel it under Background tasks."
        ) from None


@router.get("/ingest/status", response_model=Job | None)
def ingest_status():
    """The most recent ingestion job, or null if indexing has never run."""
    return rag_service.latest_ingestion()
