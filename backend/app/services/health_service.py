"""Health checks behind GET /health/checks: is the model runtime reachable, are the chat and
embedding models installed, is there enough free disk space, and is OCR available.

Every check has a status (ok, warning, error, or unknown when it couldn't run) and a title. A check
that found a problem also says what it means and how to fix it, for the banner in the desktop.
"""

import os
import shutil

import requests

from app.core.config import CHAT_MODEL, DB_PATH, EMBEDDING_MODEL, MIN_FREE_DISK_MB, OLLAMA_URL, TESSERACT_PATH
from app.core.friendly_errors import RUNTIME_DOWN, START_RUNTIME, install_model_fix, missing_model_title, runtime_down_detail

TAGS_TIMEOUT_SECONDS = 3


def _check(check_id, status, title, detail=None, fix=None):
    return {"id": check_id, "status": status, "title": title, "detail": detail, "fix": fix}


def _installed_models():
    response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=TAGS_TIMEOUT_SECONDS)
    response.raise_for_status()
    return {model["name"] for model in response.json().get("models", [])}


def _is_installed(model, installed):
    # Ollama treats a name without a tag as name:latest.
    return model in installed or (":" not in model and f"{model}:latest" in installed)


def check_models():
    """The model runtime check, then one check per required model."""
    models = (
        ("chat_model", CHAT_MODEL, "Chat won't work without it."),
        ("embedding_model", EMBEDDING_MODEL, "Indexing and “Use my docs” won't work without it."),
    )
    try:
        installed = _installed_models()
    except requests.RequestException:
        runtime = _check("model_runtime", "error", RUNTIME_DOWN, runtime_down_detail(), f"{START_RUNTIME}. Then click Check again.")
        return [runtime] + [
            _check(check_id, "unknown", f"{model} not checked", "Ollama must be running to check this.") for check_id, model, _ in models
        ]

    checks = [_check("model_runtime", "ok", "Model runtime is running", f"Ollama at {OLLAMA_URL}")]
    for check_id, model, consequence in models:
        if _is_installed(model, installed):
            checks.append(_check(check_id, "ok", f"{model} is installed"))
        else:
            checks.append(_check(check_id, "error", missing_model_title(model), consequence, install_model_fix(model)))
    return checks


def check_disk():
    folder = os.path.dirname(os.path.abspath(DB_PATH))
    free_mb = shutil.disk_usage(folder).free / 1024**2
    if free_mb >= MIN_FREE_DISK_MB:
        return _check("disk_space", "ok", "Enough free disk space", f"{free_mb / 1024:.1f} GB free")
    return _check(
        "disk_space",
        "warning",
        "Low disk space",
        f"Only {free_mb:.0f} MB free on the drive where Locali keeps its index and database ({folder}). Indexing may fail.",
        "Free up space on that drive.",
    )


def check_ocr():
    if os.path.isfile(TESSERACT_PATH) or shutil.which(TESSERACT_PATH):
        return _check("ocr", "ok", "OCR is available")
    return _check(
        "ocr",
        "warning",
        "OCR not available",
        "Text inside images won't be indexed.",
        f"Install Tesseract OCR, or set tesseract_path in backend/app/core/config.py (now {TESSERACT_PATH}).",
    )


def run_checks():
    """All checks, plus an overall status: the worst one found."""
    checks = [*check_models(), check_disk(), check_ocr()]
    statuses = {check["status"] for check in checks}
    status = "error" if "error" in statuses else "warning" if "warning" in statuses else "ok"
    return {"status": status, "checks": checks}
