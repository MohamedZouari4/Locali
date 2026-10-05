"""Turns low-level errors about the model runtime into messages a user can act on, for chat, jobs,
API errors and the health checks: Ollama not reachable, or a model that isn't installed.

describe_error() returns None for anything it doesn't recognise, so callers fall back to the original.
"""

import requests

from app.core.config import CHAT_MODEL, EMBEDDING_MODEL, OLLAMA_URL

RUNTIME_DOWN = "Model runtime not running — start it"
START_RUNTIME = "Open the Ollama app, or run: ollama serve"


def runtime_down_detail():
    return f"Locali can't reach Ollama at {OLLAMA_URL}."


def missing_model_title(model):
    return f"Model {model} isn't installed"


def install_model_fix(model):
    return f"Run: ollama pull {model}"


def _chain(error):
    # The error itself, then what caused it (e.g. a RuntimeError raised from a ConnectionError).
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        yield error
        error = error.__cause__ or error.__context__


def _ollama_url(error):
    url = getattr(getattr(error, "request", None), "url", None) or ""
    return url if url.startswith(OLLAMA_URL.rstrip("/")) else None


def describe_error(error):
    """A user-facing message for a model-runtime error anywhere in the cause chain, or None."""
    for cause in _chain(error):
        url = _ollama_url(cause)
        if url is None:
            continue
        if isinstance(cause, requests.ConnectionError):
            return f"{RUNTIME_DOWN}. {runtime_down_detail()} {START_RUNTIME}."
        response = getattr(cause, "response", None)
        if isinstance(cause, requests.HTTPError) and response is not None and response.status_code == 404:
            if url.endswith("/api/chat"):
                return f"{missing_model_title(CHAT_MODEL)}, so chat can't answer. {install_model_fix(CHAT_MODEL)}"
            if url.endswith(("/api/embed", "/api/embeddings")):
                return (
                    f"{missing_model_title(EMBEDDING_MODEL)}, so files can't be indexed or searched. {install_model_fix(EMBEDDING_MODEL)}"
                )
    return None
