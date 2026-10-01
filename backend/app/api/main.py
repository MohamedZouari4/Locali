"""FastAPI application: registers request logging, the global error handler, and the chat,
ingestion, search and file routers.

Every route except /health and /favicon.ico requires the bearer token.
Run from the backend folder with `python -m uvicorn app.api.main:app`.
"""

import os

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse

from app.api.deps import verify_token
from app.api.errors import global_exception_handler
from app.api.middleware import RequestLoggingMiddleware
from app.api.routers import chat, files, ingest, search
from app.core.config import REPO_ROOT

app = FastAPI(
    title="Local AI Workspace Assistant",
    version="1.0",
    description="A local-first AI assistant with document Q&A and safe file operations.",
)

app.add_middleware(RequestLoggingMiddleware)
app.add_exception_handler(Exception, global_exception_handler)

app.include_router(chat.router, tags=["Chat"], dependencies=[Depends(verify_token)])
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
