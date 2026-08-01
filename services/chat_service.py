from orchestrator import ask

def get_answer(message, use_docs=False, project=None):
    answer, sources, _ = ask(message, use_docs=use_docs, project=project)
    return {"response": answer, "sources": sources}
