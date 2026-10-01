"""Turns text into embedding vectors with the local Ollama embedding model, retrying with backoff."""

import time

import requests

from app.core.config import EMBEDDING_MODEL, OLLAMA_URL

EMBED_TIMEOUT = 30
EMBED_MAX_RETRIES = 3
EMBED_BACKOFF_BASE = 1.5


def _post_with_retries(endpoint, payload, result_key, name):
    last_exc = None
    for attempt in range(1, EMBED_MAX_RETRIES + 1):
        try:
            resp = requests.post(f"{OLLAMA_URL}{endpoint}", json=payload, timeout=EMBED_TIMEOUT)
            resp.raise_for_status()
            return resp.json()[result_key]
        except (requests.exceptions.RequestException, KeyError) as exc:
            last_exc = exc
            if attempt < EMBED_MAX_RETRIES:
                time.sleep(EMBED_BACKOFF_BASE**attempt)
    raise RuntimeError(f"{name}() failed after {EMBED_MAX_RETRIES} attempts") from last_exc


def embed(text):
    return _post_with_retries("/api/embeddings", {"model": EMBEDDING_MODEL, "prompt": text}, "embedding", "embed")


def embed_batch(texts):
    return _post_with_retries("/api/embed", {"model": EMBEDDING_MODEL, "input": texts}, "embeddings", "embed_batch")
