"""Answers a user question with the local chat model.

Optionally adds retrieved document context to the prompt, then lets the model call the sandboxed
file tools (list, move, create folder, organize, find empty files) for up to six rounds.

When file contents are in the prompt, the tools are not offered: text inside an indexed file
must never be able to trigger a file operation.
"""

import json
import sys

import requests

from app.ai.chat.prompts import SYSTEM_PROMPT, TOOL_LIMIT_MESSAGE, build_prompt
from app.ai.chat.tool_schema import AVAILABLE_TOOLS, TOOLS_SCHEMA
from app.ai.retrieval import retrieve
from app.chat_events import SourcesEvent, TokenEvent
from app.core.config import CHAT_MODEL, OLLAMA_URL
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


def _chat_payload(messages, with_tools, stream):
    payload = {"model": CHAT_MODEL, "messages": messages, "stream": stream}
    if with_tools:
        payload["tools"] = TOOLS_SCHEMA
    return payload


def _run_tool_calls(tool_calls, messages):
    # Runs each requested tool and appends its result to the messages.
    for call in tool_calls:
        name = call["function"]["name"]
        arguments = call["function"]["arguments"]
        if DEBUG:
            print(f"[DEBUG] Tool call requested: {name}({arguments})")
        fn = AVAILABLE_TOOLS.get(name)
        if fn is None:
            result = f"Error: unknown tool '{name}'"
        else:
            try:
                result = fn(**arguments)
            except PermissionError as e:
                result = f"Blocked: {e}"
                log_action(f"blocked {name}({arguments}): {e}", success=False)
            except FileNotFoundError as e:
                result = f"Not found: {e}"
            except Exception as e:
                result = f"Error running {name}: {e}"
        if DEBUG:
            print(f"[DEBUG] Tool call result: {result}")
        messages.append({"role": "tool", "content": str(result)})


def ask(query, use_docs=False, project=None):
    messages, sources = _build_messages(query, use_docs, project)
    with_tools = not sources
    used_tools = False
    answer = TOOL_LIMIT_MESSAGE
    for _ in range(MAX_TOOL_ROUNDS):
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=_chat_payload(messages, with_tools, stream=False))
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
        _run_tool_calls(tool_calls, messages)

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
