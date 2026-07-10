from fastapi import APIRouter
from ingest import ingest_all, reset_index

router = APIRouter()

@router.post("/ingest")
async def trigger_ingest(full_reset: bool = False):
    """Trigger the ingestion process for all files in the allowed workspace."""
    if full_reset:
        reset_index()
    ingest_all()
    return {"status": "Ingestion process completed."}
