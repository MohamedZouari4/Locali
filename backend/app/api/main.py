"""FastAPI application: registers request logging, the global error handler, and the chat,
conversation, job, ingestion, search and file routers, and runs the background job worker while
the server is up. Starting it with LOCALI_DEMO_JOBS=1 adds the `demo` job kind (app/jobs/demo.py).

Every route except /health and /favicon.ico requires the bearer token.
Run from the backend folder with `python -m uvicorn app.api.main:app`.
"""

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse

from app import chat_events, job_events
from app.api.deps import verify_token
from app.api.errors import global_exception_handler
from app.api.middleware import RequestLoggingMiddleware
from app.api.routers import chat, conversations, files, ingest, jobs, search
from app.core.config import REPO_ROOT
from app.jobs import demo, worker


@asynccontextmanager
async def lifespan(_app):
    if os.environ.get("LOCALI_DEMO_JOBS") == "1":
        demo.register()
    # Jobs a previous run left running are marked failed, then queued jobs start running.
    await asyncio.to_thread(worker.start_worker)
    yield
    await asyncio.to_thread(worker.stop_worker)


app = FastAPI(
    lifespan=lifespan,
    title="Local AI Workspace Assistant",
    version="1.0",
    description="A local-first AI assistant with document Q&A and safe file operations.",
)

app.add_middleware(RequestLoggingMiddleware)
app.add_exception_handler(Exception, global_exception_handler)

app.include_router(chat.router, tags=["Chat"], dependencies=[Depends(verify_token)])
app.include_router(conversations.router, tags=["Conversations"], dependencies=[Depends(verify_token)])
app.include_router(jobs.router, tags=["Jobs"], dependencies=[Depends(verify_token)])
app.include_router(ingest.router, tags=["Ingestion"], dependencies=[Depends(verify_token)])
app.include_router(search.router, tags=["Search"], dependencies=[Depends(verify_token)])
app.include_router(files.router, tags=["Files"], dependencies=[Depends(verify_token)])


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    favicon_path = os.path.join(REPO_ROOT, "desktop", "public", "favicon.svg")
    return FileResponse(favicon_path, media_type="image/svg+xml")


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok"}


def _openapi_with_chat_events():
    # FastAPI leaves WebSockets out of OpenAPI, so add the chat and job event schemas by hand.
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    components.update(chat_events.openapi_schemas())
    components.update(job_events.openapi_schemas())
    schema["x-websockets"] = {
        "/chat/stream": {
            "subprotocol": chat_events.CHAT_SUBPROTOCOL,
            "version": chat_events.CHAT_EVENTS_VERSION,
            "request": {"$ref": "#/components/schemas/ChatStreamRequest"},
            "events": {"$ref": "#/components/schemas/ChatEvent"},
            "docs": "docs/CHAT_EVENTS.md",
        },
        "/jobs/events": {
            "subprotocol": job_events.JOB_SUBPROTOCOL,
            "version": job_events.JOB_EVENTS_VERSION,
            "events": {"$ref": "#/components/schemas/JobEvent"},
            "docs": "docs/JOB_EVENTS.md",
        },
    }
    app.openapi_schema = schema
    return schema


app.openapi = _openapi_with_chat_events
