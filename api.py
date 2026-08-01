from fastapi import FastAPI, Depends
from routers import chat, ingest_router, search, files
from services.auth_dependency import verify_token
from services.middleware import RequestLoggingMiddleware
from services.error_handlers import global_exception_handler

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


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok"}