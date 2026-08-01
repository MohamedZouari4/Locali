import time
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from services.logging_config import logger


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request_id = str(uuid.uuid4())[:8]
        start = time.time()

        logger.info(f"[{request_id}] {request.method} {request.url.path} - started")

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.time() - start) * 1000, 1)
            logger.info(
                f"[{request_id}] {request.method} {request.url.path} "
                f"- unhandled exception - {duration_ms}ms"
            )
            raise

        duration_ms = round((time.time() - start) * 1000, 1)
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} "
            f"- {response.status_code} - {duration_ms}ms"
        )
        response.headers["X-Request-ID"] = request_id
        return response
    