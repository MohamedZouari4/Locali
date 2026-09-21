"""
LOCALI — P2-E3-T3 · Cross-encoder re-ranking  (LOC-48)

Sits between hybrid merge (P2-E3-T2) and context assembly (P1-E4-T2).
Pure function: takes the merged candidate list, returns a shorter, better-ordered one.

Decision on record: ms-marco-MiniLM-L-6-v2 on CPU. Ollama holds VRAM during chat,
so the reranker stays off the GPU.

Failure policy: never raise into the retrieval path. Any problem — model missing,
load error, timeout — degrades to the merged order from P2-E3-T2.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Sequence

from app.config import (
    RERANK_ENABLED,
    RERANK_MODEL,
    RERANK_TOP_N,
    RERANK_MAX_LENGTH,
    RERANK_BATCH_SIZE,
    RERANK_TIMEOUT_MS,
)

log = logging.getLogger(__name__)

_model = None
_model_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rerank")


def _load_model():
    """Lazy singleton. Import is local so a CLI run that never reranks
    doesn't pay torch's import cost at startup."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import CrossEncoder

                log.info("Loading cross-encoder %s on CPU", RERANK_MODEL)
                _model = CrossEncoder(
                    RERANK_MODEL,
                    max_length=RERANK_MAX_LENGTH,
                    device="cpu",
                )
    return _model


def warmup() -> None:
    """Pay the model-load cost at service start, not on the user's first question.
    Call from the FastAPI startup hook (P2-E1) or at CLI boot."""
    if not RERANK_ENABLED:
        return
    try:
        _load_model().predict([("warmup", "warmup")])
        log.info("Reranker ready")
    except Exception:
        log.exception("Reranker warmup failed; retrieval will use merged order")


def _text_of(candidate: Any) -> str:
    if isinstance(candidate, (tuple, list)):
        return str(candidate[0]) if candidate else ""
    if isinstance(candidate, dict):
        return candidate.get("text") or candidate.get("document") or ""
    return getattr(candidate, "text", "") or ""


def _chunk_id_of(candidate: Any) -> str:
    """Deterministic tiebreak key. Preserves the P2-E3-T2 guarantee
    through the second pass."""
    if isinstance(candidate, (tuple, list)):
        return str(candidate[1]) if len(candidate) > 1 else ""
    if isinstance(candidate, dict):
        return str(candidate.get("chunk_id") or candidate.get("id") or "")
    return str(getattr(candidate, "chunk_id", "") or getattr(candidate, "id", ""))


def rerank(query: str, candidates: Sequence[Any], top_n: int = RERANK_TOP_N) -> list:
    """Re-score merged candidates with the cross-encoder and return the best top_n.

    Cross-encoder scores REPLACE the merged ordering. They are never blended with
    the RRF/merge weighting — the two are on different scales and averaging them
    is meaningless.
    """
    if not candidates:
        return []
    if not RERANK_ENABLED:
        return list(candidates[:top_n])

    pairs = [(query, _text_of(c)) for c in candidates]

    try:
        model = _load_model()
        future = _executor.submit(model.predict, pairs, batch_size=RERANK_BATCH_SIZE)
        scores = future.result(timeout=RERANK_TIMEOUT_MS / 1000)
    except FutureTimeout:
        # NOTE: the inference thread keeps running to completion; its result is
        # discarded. This bounds the user's wait, not the CPU spend. If timeouts
        # are frequent, lower RERANK_CANDIDATES rather than RERANK_TIMEOUT_MS.
        log.warning(
            "Reranker exceeded %d ms on %d candidates; keeping merged order",
            RERANK_TIMEOUT_MS,
            len(candidates),
        )
        return list(candidates[:top_n])
    except Exception:
        log.exception("Reranker failed; keeping merged order")
        return list(candidates[:top_n])

    ranked = sorted(
        zip(scores, candidates),
        key=lambda pair: (-float(pair[0]), _chunk_id_of(pair[1])),
    )

    if log.isEnabledFor(logging.DEBUG):
        for score, cand in ranked[:top_n]:
            log.debug("rerank %+.3f  %s", float(score), _chunk_id_of(cand))

    return [candidate for _, candidate in ranked[:top_n]]