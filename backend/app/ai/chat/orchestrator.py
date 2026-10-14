"""Answers a user question with the local chat model.

Optionally adds retrieved document context to the prompt, then lets the model call the tools in the
registry (app/tools/registry.py) for up to six rounds, offering at most MAX_TOOLS_PER_STEP of them.

When file contents are in the prompt, no tools are offered, and the registry runs only offered tools:
text inside an indexed file must never be able to trigger a file operation. Each tool result reaches
the model as JSON: the result, or an error with one of the fixed codes in app/tools/errors.py.
The model's answer is returned with the sources it used, and whether it called any tools.
"""

import json
import sys

import requests

from app.ai.chat.prompts import SYSTEM_PROMPT, TOOL_LIMIT_MESSAGE, build_prompt
from app.ai.chat.tool_schema import AVAILABLE_TOOLS, TOOLS_SCHEMA
from app.ai.retrieval import retrieve
from app.chat_events import SourcesEvent, TokenEvent
from app.core.config import CHAT_MODEL, MAX_TOOLS_PER_STEP, OLLAMA_URL
from app.tools import registry
from app.tools.audit_log import log_action

DEBUG = "--debug" in sys.argv
MAX_TOOL_ROUNDS = 6


def build_context(query, k=4, project=None):
    # Search the ingested documents for the k chunks most relevant to the query.
    # `project` optionally pins the search to sources whose path contains that substring.
    results = retrieve(query, k, project=project)
    if DEBUG:
        print(f"\n[DEBUG] Retrieved {len(results)} chunks for query: {query!r}")
        for chunk, source in results:
            print(f"[DEBUG]   source={source}  chunk={chunk[:80]!r}...")
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


def _build_messages(query, use_docs, project):
    # Returns the chat history to send to the model and the sources used to build the context.
    sources = []
    if use_docs:
        context_block, sources = build_context(query, project=project)
        prompt = build_prompt(query, context_block)
    else:
        prompt = query
    if DEBUG:
        print(f"\n[DEBUG] Final prompt sent to model:\n{prompt[:1000]}\n")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    return messages, sources


def _offered_tools(sources):
    # The tool cards to offer: none while retrieved file contents are in the prompt.
    return [] if sources else registry.offer(MAX_TOOLS_PER_STEP)


def _chat_payload(messages, offered, stream):
    payload = {"model": CHAT_MODEL, "messages": messages, "stream": stream}
    if offered:
        payload["tools"] = [registry.schema(card) for card in offered]
    return payload


def _run_tool_calls(tool_calls, messages, offered):
    # Runs each requested tool through the registry and appends its result to the messages.
    offered_names = {card.name for card in offered}
    for call in tool_calls:
        name = call["function"]["name"]
        arguments = call["function"]["arguments"]
        if DEBUG:
            print(f"[DEBUG] Tool call requested: {name}({arguments})")
        result = registry.run(name, arguments, offered_names)
        if DEBUG:
            print(f"[DEBUG] Tool call result: {result}")
        messages.append({"role": "tool", "content": json.dumps(result, ensure_ascii=False, default=str)})


def ask(query, use_docs=False, project=None):
    messages, sources = _build_messages(query, use_docs, project)
    offered = _offered_tools(sources)
    used_tools = False
    answer = TOOL_LIMIT_MESSAGE
    for _ in range(MAX_TOOL_ROUNDS):
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=_chat_payload(messages, offered, stream=False))
        resp.raise_for_status()
        message = resp.json()["message"]

        if DEBUG:
            print(f"[DEBUG] Raw model message: {message}\n")

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            answer = message["content"]
            break

        used_tools = True
        messages.append(message)
        _run_tool_calls(tool_calls, messages, offered)

    return answer, sources, used_tools


def ask_stream(query, use_docs=False, project=None):
    # Same as ask(), but yields the answer token by token, then an event with the sources.
    # The caller saves the reply and ends the stream with a done event.
    messages, sources = _build_messages(query, use_docs, project)
    with_tools = not sources
    answer = TOOL_LIMIT_MESSAGE
    for _ in range(MAX_TOOL_ROUNDS):
        tool_calls = []
        parts = []
        # `with` closes the Ollama request if the generator is closed early (the client left),
        # which makes Ollama stop generating.
        with requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=_chat_payload(messages, with_tools, stream=True),
            stream=True,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line.decode("utf-8"))
                message = chunk.get("message", {})
                tool_calls.extend(message.get("tool_calls") or [])
                text = message.get("content")
                if text:
                    parts.append(text)
                    yield TokenEvent(text=text)
                if chunk.get("done"):
                    break

        if not tool_calls:
            answer = "".join(parts)
            break

        messages.append({"role": "assistant", "content": "".join(parts), "tool_calls": tool_calls})
        _run_tool_calls(tool_calls, messages)
    else:
        # The loop ran out of rounds without a final answer.
        yield TokenEvent(text=answer)

    yield SourcesEvent(sources=sources)
