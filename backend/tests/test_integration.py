"""P1-E7-T3: integration test - ingest fixture files, ask a known question,
verify the answer's sources include the fixture that actually answers it.

This hits a real local Ollama server (for embeddings + chat) and a real,
temporary Chroma store, so it's slower and less deterministic than the unit
tests in test_tools.py. It's skipped automatically if Ollama or the models
configured in app.core.config aren't available.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import requests

from app.ai.chat import orchestrator
from app.ai.ingestion import pipeline, store
from app.ai.retrieval import sparse_retriever
from app.core import config

MARKER = "PINEAPPLE-QUASAR-77"


def _ollama_ready():
    try:
        resp = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=2)
        resp.raise_for_status()
    except Exception:
        return False, "Ollama is not reachable at OLLAMA_URL"
    names = {m.get("name") for m in resp.json().get("models", [])}
    missing = {config.CHAT_MODEL, config.EMBEDDING_MODEL} - names
    if missing:
        return False, f"Ollama is missing required model(s): {', '.join(missing)}"
    return True, ""


@unittest.skipUnless(*_ollama_ready())
class TestIngestAskCitation(unittest.TestCase):
    def setUp(self):
        self.fixtures_dir = tempfile.mkdtemp(prefix="fixtures_")
        self.vector_dir = tempfile.mkdtemp(prefix="vector_")

        with open(os.path.join(self.fixtures_dir, "notes.md"), "w", encoding="utf-8") as f:
            f.write(f"# Project Notes\n\nThe internal codename for this project is {MARKER}. It is unrelated to any other project.\n")

        # The walker and the store read SCAN_DRIVES / VECTOR_DIR from config at call time,
        # so patching config and reopening the collection is enough; no module reloads.
        self._patches = [
            patch.object(config, "SCAN_DRIVES", [self.fixtures_dir]),
            patch.object(config, "VECTOR_DIR", self.vector_dir),
        ]
        for p in self._patches:
            p.start()
        store.close_collection()
        sparse_retriever.invalidate_caches()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        store.close_collection()
        sparse_retriever.invalidate_caches()

        shutil.rmtree(self.fixtures_dir, ignore_errors=True)
        shutil.rmtree(self.vector_dir, ignore_errors=True)

    def test_ingest_then_ask_returns_cited_answer(self):
        pipeline.ingest_all()

        answer, sources, _used_tools = orchestrator.ask("What is the internal codename for this project?", use_docs=True)

        self.assertTrue(sources, "expected at least one cited source")
        self.assertTrue(
            any("notes.md" in s for s in sources),
            f"expected notes.md among cited sources, got: {sources}",
        )
        self.assertIn(MARKER, answer)


if __name__ == "__main__":
    unittest.main()
