import importlib

import app.AI.retrieval.dense_retriever as dense_retriever
import app.AI.retrieval.hybrid_retriever as hybrid_retriever
import app.AI.retrieval.retriever as package_retriever
import app.AI.retrieval.sparse_retriever as sparse_retriever


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

