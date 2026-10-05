"""Background job routes: start a job, list jobs, read one, cancel one, and the /jobs/events
WebSocket that pushes progress (see app/job_events.py and docs/JOB_EVENTS.md).

Only kinds registered with the worker can be started, so a client can't run arbitrary code.
"""

import contextlib
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.core.security import is_valid_token
from app.db import database
from app.job_events import JOB_SUBPROTOCOL, Job, JobState, stream_job_events
from app.jobs import worker

router = APIRouter(prefix="/jobs")


class StartJobRequest(BaseModel):
    kind: str
    params: dict[str, Any] = Field(default_factory=dict)
    project: str = Field("default", min_length=1, max_length=200)


def _job_or_404(job_id):
    job = database.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("", status_code=202, response_model=Job)
def start_job(req: StartJobRequest):
    if req.kind not in worker.HANDLERS:
        available = ", ".join(sorted(worker.HANDLERS)) or "none"
        raise HTTPException(status_code=422, detail=f"Unknown job kind '{req.kind}'. Available: {available}")
    try:
        return database.get_job(worker.submit(req.kind, req.params, req.project))
    except worker.JobAlreadyActive as error:
        raise HTTPException(status_code=409, detail=str(error)) from None


@router.get("", response_model=list[Job])
def list_jobs(state: list[JobState] | None = Query(None), limit: int = Query(50, ge=1, le=200)):
    """Newest first. Repeat `state` to filter, e.g. `?state=queued&state=running`."""
    return database.list_jobs(state, limit)


@router.get("/{job_id}", response_model=Job)
def get_job(job_id: str):
    return _job_or_404(job_id)


@router.post("/{job_id}/cancel", response_model=Job)
def cancel_job(job_id: str):
    """A queued job is cancelled at once; a running job stops at its next check (cancel_requested)."""
    if database.cancel_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_or_404(job_id)


@router.websocket("/events")
async def job_events(websocket: WebSocket):
    authorization = websocket.headers.get("authorization", "")
    if not is_valid_token(authorization.removeprefix("Bearer ").strip()):
        await websocket.close(code=1008, reason="Invalid API token")
        return

    requested = websocket.scope.get("subprotocols", [])
    if requested and JOB_SUBPROTOCOL not in requested:
        await websocket.close(code=1008, reason=f"Unsupported protocol, use {JOB_SUBPROTOCOL}")
        return

    await websocket.accept(subprotocol=JOB_SUBPROTOCOL if requested else None)
    with contextlib.suppress(WebSocketDisconnect):  # the client left; nothing to clean up
        await stream_job_events(websocket)
