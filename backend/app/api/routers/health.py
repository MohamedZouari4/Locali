"""GET /health/checks: the detailed health checks (model runtime, models, disk space, OCR), each with
a fix when something is wrong. GET /health in app/api/main.py stays a fast, public liveness check.
"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import health_service

router = APIRouter(prefix="/health")


class HealthCheck(BaseModel):
    id: str
    status: Literal["ok", "warning", "error", "unknown"]
    title: str
    detail: str | None = None
    fix: str | None = None


class HealthReport(BaseModel):
    status: Literal["ok", "warning", "error"]
    checks: list[HealthCheck]


@router.get("/checks", response_model=HealthReport)
def health_checks():
    return health_service.run_checks()
