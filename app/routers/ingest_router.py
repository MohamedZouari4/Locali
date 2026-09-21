from fastapi import APIRouter
from app.AI.ingest import ingest_all, reset_index
from app.services import rag_service

router = APIRouter()

@router.post("/ingest")
def trigger_ingest(full_reset: bool = False):
    return rag_service.run_ingestion(full_reset=full_reset)
