import importlib

import app.AI.retrieval.retriever as package_retriever
from app.AI.retrieval import dense_retriever, hybrid_retriever, sparse_retriever

# Keep app.AI.retriever import-compatible while allowing config-driven reloads in tests.
for module in (
    dense_retriever,
    sparse_retriever,
    hybrid_retriever,
    package_retriever,
):
    importlib.reload(module)

retrieve = package_retriever.retrieve

__all__ = ["retrieve"]
