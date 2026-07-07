import requests
from config import CHAT_MODEL, OLLAMA_URL
from retriever import retrieve

def build_context(query, k=4, project=None):
    # Vector-search the ingested documents for the k chunks most relevant to the query.
    # `project` optionally pins the search to sources whose path contains that substring.
    results = retrieve(query, k, project=project)
    if not results:
        # Nothing relevant found (e.g. empty index) -> no context to inject.
        return "", []
    labeled_chunks = []
    sources = []
    for chunk, source in results:
        # Tag each chunk with its source file so the LLM (and the caller) can cite it.
        labeled_chunks.append(f"Source: {source}\n{chunk}")
        sources.append(source)

    # Join chunks into a single block, separated so the LLM can tell them apart.
    context_block = "\n\n---\n\n".join(labeled_chunks)
    return context_block, sources

def build_prompt(query, context_block):
    if not context_block:
        # No retrieved context -> fall back to asking the raw question.
        return query
    # Wrap the retrieved context and instructions around the user's question,
    # nudging the LLM to answer from the provided sources instead of hallucinating.
    return (
        "Use the following context from the user's files to answer the question. "
        "If the context does not contain the answer, say so rather than guessing.\n\n"
        f"{context_block}\n\n"
        f"Question: {query}"
    )
def ask(query, use_docs=False, project=None):
    sources = []
    if use_docs:
        context_block, sources = build_context(query, project=project)
        prompt = build_prompt(query, context_block)
    else:
        prompt = query
    
    playload = {
        "model": CHAT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False
    }

    resp = requests.post(f"{OLLAMA_URL}/api/chat", json=playload)
    resp.raise_for_status()
    answer = resp.json()["message"]["content"]

    return answer, sources
