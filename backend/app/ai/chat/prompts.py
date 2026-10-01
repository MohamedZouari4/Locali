"""Prompt text for the chat model: the system prompt and the wrapper that adds retrieved context."""

SYSTEM_PROMPT = (
    "You are a local assistant with access to tools for file operations: "
    "listing files, moving/renaming files, creating folders, organizing files by "
    "extension, and finding empty files. "
    "Answer questions, explanations, summaries, rewriting requests, and job "
    "application or profile writing requests directly in plain text. These "
    "requests do not require a tool. Never claim that you cannot generate text "
    "because the available tools are file-operation tools. "
    "Some requests require calling more than one tool in sequence to complete — "
    "for example, first finding which files match a condition, then moving each "
    "one. Call tools directly instead of explaining how to do it manually, and "
    "keep calling tools across turns until the request is fully done. "
    "Use tools only when the user asks you to perform a file operation."
)

TOOL_LIMIT_MESSAGE = "Reached the tool-call limit before finishing this request."


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
