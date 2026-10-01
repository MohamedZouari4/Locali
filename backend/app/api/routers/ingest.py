"""Ingestion endpoints. POST /ingest starts a background run (optionally clearing the index first
with `full_reset=true`) and returns 202, or 409 if one is already running. GET /ingest/status
reports progress and the last run's counts.
"""

from fastapi import APIRouter, HTTPException

from app.services import rag_service

router = APIRouter()


@router.post("/ingest", status_code=202)
def trigger_ingest(full_reset: bool = False):
    if not rag_service.start_ingestion(full_reset=full_reset):
        raise HTTPException(status_code=409, detail="Ingestion is already running")
    return rag_service.ingestion_status()


@router.get("/ingest/status")
def ingest_status():
    return rag_service.ingestion_status()
