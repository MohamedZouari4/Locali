"""FastAPI application: registers request logging, the global error handler, and the chat,
ingestion, search and file routers.

Every route except /health and /favicon.ico requires the bearer token.
Run from the backend folder with `python -m uvicorn app.api.main:app`.
"""

import os

from fastapi import Depends, FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse

from app import chat_events
from app.api.deps import verify_token
from app.api.errors import global_exception_handler
from app.api.middleware import RequestLoggingMiddleware
from app.api.routers import chat, conversations, files, ingest, search
from app.core.config import REPO_ROOT

app = FastAPI(
    title="Local AI Workspace Assistant",
    version="1.0",
    description="A local-first AI assistant with document Q&A and safe file operations.",
)

app.add_middleware(RequestLoggingMiddleware)
app.add_exception_handler(Exception, global_exception_handler)

app.include_router(chat.router, tags=["Chat"], dependencies=[Depends(verify_token)])
app.include_router(conversations.router, tags=["Conversations"], dependencies=[Depends(verify_token)])
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
    # FastAPI leaves WebSockets out of OpenAPI, so add the chat event schemas by hand.
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)
    schema.setdefault("components", {}).setdefault("schemas", {}).update(chat_events.openapi_schemas())
    schema["x-websockets"] = {
        "/chat/stream": {
            "subprotocol": chat_events.CHAT_SUBPROTOCOL,
            "version": chat_events.CHAT_EVENTS_VERSION,
            "request": {"$ref": "#/components/schemas/ChatStreamRequest"},
            "events": {"$ref": "#/components/schemas/ChatEvent"},
            "docs": "docs/CHAT_EVENTS.md",
        }
    }
    app.openapi_schema = schema
    return schema


app.openapi = _openapi_with_chat_events
