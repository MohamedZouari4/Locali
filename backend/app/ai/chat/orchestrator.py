"""Answers a user question with the local chat model.

Optionally adds retrieved document context to the prompt, then lets the model call the tools in the
registry (app/tools/registry.py) for up to six rounds, offering at most MAX_TOOLS_PER_STEP of them.

When file contents are in the prompt, no tools are offered, and the registry runs only offered tools:
text inside an indexed file must never be able to trigger a file operation. Each tool result reaches
the model as JSON: the result, or an error with one of the fixed codes in app/tools/errors.py.
The model's answer is returned with the sources it used, and whether it called any tools.
`project_id` is the chat's project: project tools work on it, and only it, and aren't offered without one.

Once a tool has returned text from the user's files (search_text, read_file), only read tools stay offered for the rest
of the answer, including later calls in the same batch, for the same reason.

`history` is the conversation's earlier questions and answers (database.get_history), placed between the system
prompt and the new question. Tool results aren't part of it: they were never saved, and file text stays out of it.

`route` is the router's label for the question (router.py, chosen by chat_service). For a project question or a
multi-step task, the loop runs search_text with the question's words before the model's first turn, as if the
model had called it: the LangGraph spike showed qwen3:4b-instruct answering most fact questions about a project
from memory without searching. After any tool returns file text, a short user message (FILE_TEXT_REMINDER)
repeats the question and says the file text is data, so a planted instruction is never the last thing it reads.
"""

import json
import sys

import requests

from app.ai.chat.prompts import FILE_TEXT_REMINDER, SYSTEM_PROMPT, TOOL_LIMIT_MESSAGE, build_prompt
from app.ai.retrieval import retrieve
from app.chat_events import SourcesEvent, TokenEvent
from app.core.config import CHAT_MODEL, MAX_TOOLS_PER_STEP, OLLAMA_URL
from app.tools import registry

DEBUG = "--debug" in sys.argv
MAX_TOOL_ROUNDS = 6
# Routes whose questions are searched for in the project's files before the model's first turn.
SEARCH_FIRST_ROUTES = ("project_question", "multi_step")
# The search-first query is the question itself, cut to this length.
MAX_SEARCH_FIRST_CHARS = 500


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


def _build_messages(query, use_docs, project, history=None):
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
        *(history or []),
        {"role": "user", "content": prompt},
    ]
    return messages, sources


def _offered_tools(sources, project_id):
    # The tool cards to offer: none while retrieved file contents are in the prompt.
    return [] if sources else registry.offer(MAX_TOOLS_PER_STEP, project_id)


def _chat_payload(messages, offered, stream):
    payload = {"model": CHAT_MODEL, "messages": messages, "stream": stream}
    if offered:
        payload["tools"] = [registry.schema(card) for card in offered]
    return payload


def _run_tool_calls(tool_calls, messages, offered, project_id=None, question=None):
    # Runs each requested tool through the registry and appends its result to the messages. Returns the tools
    # still offered: once a tool has put file content into the messages, only read tools stay, and the
    # question is repeated after the results with the reminder that file text is data.
    file_text = False
    for call in tool_calls:
        name = call["function"]["name"]
        arguments = call["function"]["arguments"]
        if DEBUG:
            print(f"[DEBUG] Tool call requested: {name}({arguments})")
        cards = {card.name: card for card in offered}
        result = registry.run(name, arguments, set(cards), project_id)
        if result["ok"] and cards[name].returns_content:
            offered = [card for card in offered if card.access == "read"]
            file_text = True
        if DEBUG:
            print(f"[DEBUG] Tool call result: {result}")
        messages.append({"role": "tool", "content": json.dumps(result, ensure_ascii=False, default=str)})
    if file_text and question:
        messages.append({"role": "user", "content": FILE_TEXT_REMINDER.format(question=question)})
    return offered


def _search_first(question, route, messages, offered, project_id):
    # For a question about the project's files, runs search_text with the question before the model's first turn,
    # added to the messages as if the model had called it. Returns the tools still offered.
    if route not in SEARCH_FIRST_ROUTES or "search_text" not in {card.name for card in offered}:
        return offered
    call = {"function": {"name": "search_text", "arguments": {"query": question[:MAX_SEARCH_FIRST_CHARS]}}}
    messages.append({"role": "assistant", "content": "", "tool_calls": [call]})
    return _run_tool_calls([call], messages, offered, project_id, question)


def ask(query, use_docs=False, project=None, project_id=None, history=None, route=None):
    messages, sources = _build_messages(query, use_docs, project, history)
    offered = _offered_tools(sources, project_id)
    before = len(messages)
    offered = _search_first(query, route, messages, offered, project_id)
    used_tools = len(messages) > before
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
        offered = _run_tool_calls(tool_calls, messages, offered, project_id, query)

    return answer, sources, used_tools


def ask_stream(query, use_docs=False, project=None, project_id=None, history=None, route=None):
    # Same as ask(), but yields the answer token by token, then an event with the sources.
    # The caller saves the reply and ends the stream with a done event.
    messages, sources = _build_messages(query, use_docs, project, history)
    offered = _search_first(query, route, messages, _offered_tools(sources, project_id), project_id)
    answer = TOOL_LIMIT_MESSAGE
    for _ in range(MAX_TOOL_ROUNDS):
        tool_calls = []
        parts = []
        # `with` closes the Ollama request if the generator is closed early (the client left),
        # which makes Ollama stop generating.
        with requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=_chat_payload(messages, offered, stream=True),
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
        offered = _run_tool_calls(tool_calls, messages, offered, project_id, query)
    else:
        # The loop ran out of rounds without a final answer.
        yield TokenEvent(text=answer)

    yield SourcesEvent(sources=sources)
