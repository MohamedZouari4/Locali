import chromadb
from config import VECTOR_DIR
from ingest import embed


client = chromadb.PersistentClient(path=VECTOR_DIR)
collection = client.get_or_create_collection("documents")

def retrieve(query, k=4):
    """Return the k most relevant (chunk_text, source_file) pairs for a query."""
    query_vec = embed(query)
    results = collection.query(query_embeddings=[query_vec], n_results=k)
    chunks = results["documents"][0]
    sources = [m["source"] for m in results["metadatas"][0]]
    return list(zip(chunks, sources))

