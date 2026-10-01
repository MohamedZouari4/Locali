"""Tests for the Chroma store and keyword search against a temporary index: a full reset empties it,
and keyword search works on an empty index. No Ollama needed: embeddings are given directly.
"""

import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.ai.ingestion import store
from app.ai.retrieval import sparse_retriever
from app.core import config


class TempIndexTestCase(unittest.TestCase):
    def setUp(self):
        self.vector_dir = tempfile.mkdtemp(prefix="vector_test_")
        self._patch = patch.object(config, "VECTOR_DIR", self.vector_dir)
        self._patch.start()
        store.close_collection()
        sparse_retriever.invalidate_caches()

    def tearDown(self):
        self._patch.stop()
        store.close_collection()
        sparse_retriever.invalidate_caches()
        shutil.rmtree(self.vector_dir, ignore_errors=True)

    def _add(self, n):
        store.get_collection().add(
            ids=[f"c{i}" for i in range(n)],
            documents=[f"chunk number {i}" for i in range(n)],
            embeddings=[[0.1 * i, 0.2] for i in range(n)],
            metadatas=[{"source": f"/tmp/file{i}.md"} for i in range(n)],
        )


class TestResetIndex(TempIndexTestCase):
    def test_reset_removes_every_chunk(self):
        self._add(3)
        removed = store.reset_index()
        self.assertEqual(removed, 3)
        self.assertEqual(store.get_collection().count(), 0)

    def test_reset_on_empty_index_does_nothing(self):
        self.assertEqual(store.reset_index(), 0)


class TestKeywordSearch(TempIndexTestCase):
    def test_empty_index_returns_no_results(self):
        ranked_ids, _docs, _sources = sparse_retriever.bm25_search("anything", pool_size=10)
        self.assertEqual(ranked_ids, [])

    def test_invalidate_caches_picks_up_new_chunks(self):
        self.assertEqual(sparse_retriever.bm25_search("chunk", pool_size=10)[0], [])
        self._add(2)
        sparse_retriever.invalidate_caches()
        self.assertEqual(len(sparse_retriever.bm25_search("chunk", pool_size=10)[0]), 2)


if __name__ == "__main__":
    unittest.main()
