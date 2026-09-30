"""Retrieval package: hybrid dense + BM25 search followed by cross-encoder reranking. Exposes `retrieve`."""

from app.AI.retrieval.retriever import retrieve

__all__ = ["retrieve"]
