"""Job event contract for the /jobs/events WebSocket, and the Job model the /jobs routes return.
docs/JOB_EVENTS.md documents it.

The socket sends a `job` event with the whole job each time a job is queued, makes progress or
finishes, and a snapshot of the active jobs when a client connects. It finds changes by reading the
jobs table every JOB_EVENTS_POLL_SECONDS, so it also sees jobs changed by another process.
"""

import asyncio
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.core.config import JOB_EVENTS_POLL_SECONDS
from app.db import database

# Semantic version of the contract; only the major number is in the subprotocol (see chat_events.py).
JOB_EVENTS_VERSION = "1.0.0"
JOB_SUBPROTOCOL = f"locali.jobs.v{JOB_EVENTS_VERSION.split('.')[0]}"

JobState = Literal["queued", "running", "done", "failed", "cancelled"]
ACTIVE_STATES = ("queued", "running")


class Job(BaseModel):
    id: str
    kind: str
    project: str
    state: JobState
    params: dict[str, Any]
    result: Any = None
    error: str | None = None
    progress_current: int | None = None
    progress_total: int | None = Field(None, description="Unknown while null; the client shows no percentage then.")
    progress_message: str | None = None
    cancel_requested: bool = Field(description="A running job stops at its next cancellation check.")
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None


class JobEvent(BaseModel):
    """A job was queued, made progress or finished. Carries the whole job."""

    # Marks `type` as required in the published schema even though the model fills it in.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    type: Literal["job"] = "job"
    job: Job


job_event_adapter = TypeAdapter(JobEvent)


def openapi_schemas():
    """JSON schema for the job event, keyed by name, for components.schemas."""
    schema = job_event_adapter.json_schema(ref_template="#/components/schemas/{model}", mode="serialization")
    schemas = schema.pop("$defs")
    schemas["JobEvent"] = schema
    return schemas


async def _until_disconnected(websocket):
    while (await websocket.receive())["type"] != "websocket.disconnect":
        pass


async def stream_job_events(websocket, poll_seconds=None):
    """Sends a job event whenever a job changes, until the client disconnects."""
    disconnected = asyncio.create_task(_until_disconnected(websocket))
    last_sent = {}  # job id -> the job as last sent, for jobs still worth watching
    try:
        while not disconnected.done():
            jobs = {job["id"]: job for job in await asyncio.to_thread(database.list_jobs, ACTIVE_STATES, 200)}
            # Jobs that just left the active states still need their final event.
            for job_id in [job_id for job_id in last_sent if job_id not in jobs]:
                job = await asyncio.to_thread(database.get_job, job_id)
                if job is None:
                    del last_sent[job_id]
                else:
                    jobs[job_id] = job

            for job_id, job in jobs.items():
                if last_sent.get(job_id) != job:
                    await websocket.send_json(JobEvent(job=job).model_dump())
                if job["state"] in ACTIVE_STATES:
                    last_sent[job_id] = job
                else:
                    last_sent.pop(job_id, None)

            await asyncio.wait([disconnected], timeout=poll_seconds or JOB_EVENTS_POLL_SECONDS)
    finally:
        disconnected.cancel()
