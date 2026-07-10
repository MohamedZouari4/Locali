from fastapi import FastAPI
from routers import files, chat, search, ingest_router

app = FastAPI(title="Local AI Workspace Assistant", version="1.0.0")
app.include_router(files.router)
app.include_router(chat.router)
app.include_router(search.router)
app.include_router(ingest_router.router)

app.get("/health")
def health_check():
    """Health check endpoint to verify the API is running."""
    return {"status": "ok"}
