from pathlib import Path

from fastapi import FastAPI, Depends
from fastapi.responses import FileResponse
from app.routers import chat, files, ingest_router
from app.routers import search
from app.services.auth_dependency import verify_token
from app.services.middleware import RequestLoggingMiddleware
from app.services.error_handlers import global_exception_handler

app = FastAPI(
    title="Local AI Workspace Assistant",
    version="1.0",
    description="A local-first AI assistant with document Q&A and safe file operations."
)

app.add_middleware(RequestLoggingMiddleware)
app.add_exception_handler(Exception, global_exception_handler)

app.include_router(chat.router, tags=["Chat"], dependencies=[Depends(verify_token)])
app.include_router(ingest_router.router, tags=["Ingestion"], dependencies=[Depends(verify_token)])
app.include_router(search.router, tags=["Search"], dependencies=[Depends(verify_token)])
app.include_router(files.router, tags=["Files"], dependencies=[Depends(verify_token)])


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    favicon_path = Path(__file__).resolve().parent.parent / "locali-desktop" / "public" / "favicon.svg"
    return FileResponse(favicon_path, media_type="image/svg+xml")


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok"}