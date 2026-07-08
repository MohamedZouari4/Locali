"""P1-E7-T3: integration test - ingest fixture files, ask a known question,
verify the answer's sources include the fixture that actually answers it.

This hits a real local Ollama server (for embeddings + chat) and a real,
temporary Chroma store, so it's slower and less deterministic than the unit
tests in test_tools.py. It's skipped automatically if Ollama or the models
configured in config.py aren't available.
"""
import importlib
import os
import shutil
import tempfile
import unittest

import requests

import config

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
            f.write(
                "# Project Notes\n\n"
                f"The internal codename for this project is {MARKER}. "
                "It is unrelated to any other project.\n"
            )

        self._orig_scan_drives = config.SCAN_DRIVES
        self._orig_vector_dir = config.VECTOR_DIR
        config.SCAN_DRIVES = [self.fixtures_dir]
        config.VECTOR_DIR = self.vector_dir

        # ingest.py and retriever.py bind VECTOR_DIR/SCAN_DRIVES and create their
        # chromadb client/collection at *import time*, so they must be reloaded
        # after patching config for the new paths to take effect. orchestrator.py
        # imports `retrieve` by name from retriever, so it must be reloaded too.
        import ingest
        import retriever
        import orchestrator
        self.ingest = importlib.reload(ingest)
        self.retriever = importlib.reload(retriever)
        self.orchestrator = importlib.reload(orchestrator)

    def tearDown(self):
        config.SCAN_DRIVES = self._orig_scan_drives
        config.VECTOR_DIR = self._orig_vector_dir
        import ingest
        import retriever
        import orchestrator
        importlib.reload(ingest)
        importlib.reload(retriever)
        importlib.reload(orchestrator)

        shutil.rmtree(self.fixtures_dir, ignore_errors=True)
        shutil.rmtree(self.vector_dir, ignore_errors=True)

    def test_ingest_then_ask_returns_cited_answer(self):
        self.ingest.ingest_all()

        answer, sources, _used_tools = self.orchestrator.ask(
            "What is the internal codename for this project?", use_docs=True
        )

        self.assertTrue(sources, "expected at least one cited source")
        self.assertTrue(
            any("notes.md" in s for s in sources),
            f"expected notes.md among cited sources, got: {sources}",
        )
        self.assertIn(MARKER, answer)


if __name__ == "__main__":
    unittest.main()
