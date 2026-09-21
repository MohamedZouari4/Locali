from fastapi import Request
from fastapi.responses import JSONResponse
from app.services.logging_config import logger


async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. This has been logged."},
    )
