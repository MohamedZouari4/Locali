"""Catch-all exception handler: logs the error and returns a generic 500 response, or a 503 with a
message the user can act on when the model runtime is down or a model is missing."""

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.friendly_errors import describe_error
from app.core.logging import logger


async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.method} {request.url.path}: {exc}")
    friendly = describe_error(exc)
    if friendly:
        return JSONResponse(status_code=503, content={"detail": friendly})
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. This has been logged."},
    )
