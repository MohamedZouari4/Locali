"""
Tests for reranker.py  (LOC-48 / P2-E3-T3)

Run:      python -m pytest tests/test_rerank.py -v
With the real model:
          RERANK_INTEGRATION=1 python -m pytest tests/test_rerank.py -v

The unit tests never load a real cross-encoder. They stub _load_model, so they
run in milliseconds and pass on a machine that has never downloaded the weights.
That is deliberate: the failure modes worth guarding (fallback, determinism,
truncation) are all plumbing, not model quality.
"""

import os
import time

import pytest

from app.AI.retrieval import reranker


@pytest.fixture(autouse=True)
def reset_model_cache():
    """_model is a module-level singleton; leaking it between tests makes
    failures order-dependent."""
    reranker._model = None
    yield
    reranker._model = None


class FakeModel:
    """Stands in for CrossEncoder. Returns preset scores positionally."""

    def __init__(self, scores, delay=0.0, raises=None):
        self.scores = scores
        self.delay = delay
        self.raises = raises
        self.calls = 0

    def predict(self, pairs, batch_size=None):
        self.calls += 1
        if self.raises:
            raise self.raises
        if self.delay:
            time.sleep(self.delay)
        assert len(pairs) == len(self.scores), "fake scores must match candidate count"
        return list(self.scores)


def candidates(n=4):
    return [{"chunk_id": f"c{i}", "text": f"chunk {i}"} for i in range(n)]


def ids(results):
    return [c["chunk_id"] for c in results]


# --- ordering -------------------------------------------------------------

def test_reorders_by_score(monkeypatch):
    monkeypatch.setattr(reranker, "_load_model",
                        lambda: FakeModel([0.1, 0.9, 0.2, 0.5]))
    result = reranker.rerank("q", candidates(4), top_n=4)
    assert ids(result) == ["c1", "c3", "c2", "c0"]


def test_truncates_to_top_n(monkeypatch):
    monkeypatch.setattr(reranker, "_load_model",
                        lambda: FakeModel([0.1, 0.9, 0.2, 0.5]))
    result = reranker.rerank("q", candidates(4), top_n=2)
    assert ids(result) == ["c1", "c3"]


def test_ties_break_on_chunk_id(monkeypatch):
    """The P2-E3-T2 determinism guarantee has to survive the second pass."""
    monkeypatch.setattr(reranker, "_load_model", lambda: FakeModel([0.5] * 4))
    shuffled = [
        {"chunk_id": "c3", "text": "d"},
        {"chunk_id": "c1", "text": "b"},
        {"chunk_id": "c2", "text": "c"},
        {"chunk_id": "c0", "text": "a"},
    ]
    result = reranker.rerank("q", shuffled, top_n=4)
    assert ids(result) == ["c0", "c1", "c2", "c3"]


def test_identical_input_gives_identical_output(monkeypatch):
    monkeypatch.setattr(reranker, "_load_model",
                        lambda: FakeModel([0.4, 0.4, 0.9, 0.1]))
    first = ids(reranker.rerank("q", candidates(4), top_n=3))
    reranker._model = None
    monkeypatch.setattr(reranker, "_load_model",
                        lambda: FakeModel([0.4, 0.4, 0.9, 0.1]))
    second = ids(reranker.rerank("q", candidates(4), top_n=3))
    assert first == second


# --- fallback behaviour ---------------------------------------------------

def test_disabled_returns_merged_order_without_loading(monkeypatch):
    def explode():
        raise AssertionError("model must not load when RERANK_ENABLED is false")

    monkeypatch.setattr(reranker, "RERANK_ENABLED", False)
    monkeypatch.setattr(reranker, "_load_model", explode)
    result = reranker.rerank("q", candidates(4), top_n=2)
    assert ids(result) == ["c0", "c1"]


def test_model_failure_falls_back_to_merged_order(monkeypatch):
    monkeypatch.setattr(reranker, "_load_model",
                        lambda: FakeModel([], raises=RuntimeError("no weights")))
    result = reranker.rerank("q", candidates(4), top_n=3)
    assert ids(result) == ["c0", "c1", "c2"]


def test_load_failure_falls_back(monkeypatch):
    def explode():
        raise OSError("model files missing")

    monkeypatch.setattr(reranker, "_load_model", explode)
    result = reranker.rerank("q", candidates(4), top_n=3)
    assert ids(result) == ["c0", "c1", "c2"]


def test_timeout_falls_back_to_merged_order(monkeypatch):
    monkeypatch.setattr(reranker, "RERANK_TIMEOUT_MS", 50)
    monkeypatch.setattr(reranker, "_load_model",
                        lambda: FakeModel([0.1, 0.9, 0.2, 0.5], delay=0.5))
    started = time.perf_counter()
    result = reranker.rerank("q", candidates(4), top_n=2)
    elapsed = time.perf_counter() - started
    assert ids(result) == ["c0", "c1"]
    assert elapsed < 0.4, "timeout did not bound the caller's wait"


def test_empty_candidates():
    assert reranker.rerank("q", [], top_n=5) == []


# --- candidate shapes -----------------------------------------------------

class Chunk:
    def __init__(self, chunk_id, text):
        self.chunk_id = chunk_id
        self.text = text


def test_accepts_objects_not_just_dicts(monkeypatch):
    monkeypatch.setattr(reranker, "_load_model", lambda: FakeModel([0.2, 0.8]))
    result = reranker.rerank("q", [Chunk("a", "one"), Chunk("b", "two")], top_n=2)
    assert [c.chunk_id for c in result] == ["b", "a"]


def test_missing_text_field_does_not_raise(monkeypatch):
    """A malformed candidate should degrade, never crash retrieval."""
    monkeypatch.setattr(reranker, "_load_model", lambda: FakeModel([0.5, 0.5]))
    weird = [{"chunk_id": "c0"}, {"chunk_id": "c1", "text": "fine"}]
    result = reranker.rerank("q", weird, top_n=2)
    assert len(result) == 2


# --- integration (real model) ---------------------------------------------

pytestmark_integration = pytest.mark.skipif(
    not os.getenv("RERANK_INTEGRATION"),
    reason="set RERANK_INTEGRATION=1 to run against the real cross-encoder",
)


@pytestmark_integration
def test_real_model_ranks_the_obvious_answer_first():
    """Not an accuracy benchmark — a sanity check that the model is wired up
    and pointed the right way round. If this fails, the query/document order
    in the pair tuples is probably swapped."""
    query = "How does Locali restrict filesystem access?"
    cands = [
        {"chunk_id": "noise1", "text": "The CLI accepts a --verbose flag for debug logging."},
        {"chunk_id": "target", "text": "Filesystem operations are restricted to the configured workspace boundary."},
        {"chunk_id": "noise2", "text": "Embeddings are generated with nomic-embed-text via Ollama."},
        {"chunk_id": "noise3", "text": "Conversation history persists across sessions in SQLite."},
    ]
    result = reranker.rerank(query, cands, top_n=1)
    assert result[0]["chunk_id"] == "target"


@pytestmark_integration
def test_real_model_latency_is_recorded(capsys):
    """Produces the latency half of EXP-010. Reads as a test so it runs in CI,
    but its output is the point, not its assertion."""
    query = "How does Locali restrict filesystem access?"
    cands = [{"chunk_id": f"c{i}", "text": "Filesystem operations are restricted "
                                            "to the configured workspace boundary. " * 4}
             for i in range(20)]

    reranker.warmup()
    timings = []
    for _ in range(5):
        started = time.perf_counter()
        reranker.rerank(query, cands, top_n=5)
        timings.append((time.perf_counter() - started) * 1000)

    timings.sort()
    with capsys.disabled():
        print(f"\n  rerank of {len(cands)} candidates on CPU: "
              f"median {timings[len(timings) // 2]:.0f} ms, "
              f"min {timings[0]:.0f} ms, max {timings[-1]:.0f} ms")

    assert timings[len(timings) // 2] < reranker.RERANK_TIMEOUT_MS