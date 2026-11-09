"""Runs the spike's questions (questions.yaml) through one engine and model and scores them (P1-E5-T1).

  plain  today's tool loop (app/ai/chat/orchestrator.py), held to the chosen model and tools
  graph  the same loop as a LangGraph graph: a model node, and a tool node that runs every call through
         the registry, so cards, boundary checks and fixed error codes stay exactly as in the app

Both get the same system prompt, tools and round limit. Each question records the tool calls, whether the
answer holds an expected fact, the time, and failure types. Results go to logs/spike/*.jsonl (gitignored)
and a summary row is printed for docs/SPIKE_LANGGRAPH.md. The project is synthetic and on a temporary
database (fixture.py). LangSmith tracing is forced off, so nothing leaves the machine.

From backend/:
  uv run --group spike python -m scripts.spike.run --engine graph --model qwen3:4b-instruct
  uv run --group spike python -m scripts.spike.run --engine plain --tools all --only 1 11 29
"""

import argparse
import json
import os
import re
import statistics
import time
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import yaml

from app.ai.chat import orchestrator, router
from app.ai.chat.prompts import SYSTEM_PROMPT, TOOL_LIMIT_MESSAGE
from app.core.config import CHAT_MODEL, MAX_TOOLS_PER_STEP, OLLAMA_URL
from app.services import chat_service
from app.tools import registry
from scripts.spike.fixture import QUESTIONS, spike_project

RESULTS_DIR = Path(__file__).resolve().parents[3] / "logs" / "spike"
TWO_TOOLS = ("search_text", "read_file")
# Tool errors that mean the model called a tool wrongly (a made-up name, argument, path or id).
CALL_ERRORS = ("invalid_arguments", "not_available", "not_found")


def _offered(tools, project_id):
    offered = registry.offer(MAX_TOOLS_PER_STEP, project_id)
    return offered if tools == "all" else [card for card in offered if card.name in TWO_TOOLS]


def _recording_run(calls):
    """registry.run, also recording each call's tool, arguments and error code in `calls`."""
    real = registry.run

    def run(name, arguments, offered, project_id=None):
        result = real(name, arguments, offered, project_id)
        calls.append({"tool": name, "args": arguments, "code": None if result["ok"] else result["error"]["code"]})
        return result

    return run


def _plain_engine(model, cards, project_id):
    """Today's loop, held to the given model and tools, with the question routed first as the chat service does."""

    def ask(question):
        with (
            patch.object(orchestrator, "CHAT_MODEL", model),
            patch.object(router, "CHAT_MODEL", model),
            patch.object(registry, "offer", lambda limit, project_id=None: cards),
        ):
            route = chat_service.route(question, use_docs=False)
            answer, _sources, _used_tools = orchestrator.ask(question, project_id=project_id, route=route)
        return answer

    return ask


def _graph_engine(model, cards, project_id):
    """The same loop as a LangGraph graph. LangChain sends traces to LangSmith when tracing is on; it is
    forced off before LangChain is imported."""
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
    from langchain_ollama import ChatOllama
    from langgraph.errors import GraphRecursionError
    from langgraph.graph import END, START, MessagesState, StateGraph

    llm = ChatOllama(model=model, base_url=OLLAMA_URL).bind_tools([registry.schema(card) for card in cards])
    names = {card.name for card in cards}

    def call_model(state):
        return {"messages": [llm.invoke(state["messages"])]}

    def run_tools(state):
        results = []
        for call in state["messages"][-1].tool_calls:
            result = registry.run(call["name"], call["args"], names, project_id)
            results.append(ToolMessage(content=json.dumps(result, ensure_ascii=False, default=str), tool_call_id=call["id"]))
        return {"messages": results}

    def route(state):
        return "tools" if state["messages"][-1].tool_calls else END

    builder = StateGraph(MessagesState)
    builder.add_node("model", call_model)
    builder.add_node("tools", run_tools)
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", route, ["tools", END])
    builder.add_edge("tools", "model")
    graph = builder.compile()

    def ask(question):
        # Each tool round is two steps (model, tools), plus the final answer: the same limit as today's loop.
        limit = {"recursion_limit": 2 * orchestrator.MAX_TOOL_ROUNDS + 1}
        try:
            state = graph.invoke({"messages": [SystemMessage(SYSTEM_PROMPT), HumanMessage(question)]}, limit)
        except GraphRecursionError:
            return TOOL_LIMIT_MESSAGE
        return state["messages"][-1].content

    return ask


def _score(question, answer, calls):
    """Whether the right tools ran and the answer holds an expected fact, and what went wrong."""
    answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.S).strip()  # a thinking model's reasoning isn't the answer
    called = {call["tool"] for call in calls}
    allowed = set(question.get("allow_errors", []))
    bad_calls = [call for call in calls if call["code"] in CALL_ERRORS and call["code"] not in allowed]
    failures = []
    if question["tools"] and not called & set(question["tools"]):
        failures.append("wrong_tool" if called else "no_tool")
    if not question["tools"] and called:
        failures.append("needless_tool")
    failures += sorted({call["code"] for call in bad_calls})
    if answer == TOOL_LIMIT_MESSAGE:
        failures.append("round_limit")
    text = answer.casefold()
    obeyed = text.strip(" .!\n") in {word.casefold() for word in question.get("not_only", [])}
    answer_ok = any(word.casefold() in text for word in question["answer"]) and not obeyed
    if not answer_ok:
        failures.append("obeyed_file" if obeyed else "wrong_answer")
    tool_ok = not {"no_tool", "wrong_tool", "needless_tool"} & set(failures)
    return {"answer_ok": answer_ok, "tool_ok": tool_ok, "bad_calls": len(bad_calls), "failures": failures, "answer": answer}


def _summary(args, rows, out):
    seconds = sorted(row["seconds"] for row in rows)
    calls = sum(len(row["calls"]) for row in rows)
    bad = sum(row["bad_calls"] for row in rows)
    right = sum(row["answer_ok"] for row in rows)
    print("\n| engine | model | tools | answers right | right tools | valid calls | median s | p90 s |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    print(
        f"| {args.engine} | {args.model} | {args.tools} | {right}/{len(rows)} | {sum(row['tool_ok'] for row in rows)}/{len(rows)}"
        f" | {calls - bad}/{calls} | {statistics.median(seconds):.1f} | {seconds[int(0.9 * (len(seconds) - 1))]:.1f} |"
    )
    kinds = Counter(row["kind"] for row in rows)
    print("By kind:", {kind: f"{sum(row['answer_ok'] for row in rows if row['kind'] == kind)}/{n}" for kind, n in kinds.items()})
    print("Failures:", dict(Counter(failure for row in rows for failure in row["failures"]).most_common()))
    print("Details:", out)


def main():
    parser = argparse.ArgumentParser(description="Run the LangGraph spike's questions through one engine and model.")
    parser.add_argument("--engine", choices=("plain", "graph"), required=True)
    parser.add_argument("--model", default=CHAT_MODEL)
    tools_help = "two: search_text and read_file; all: what a project chat gets"
    parser.add_argument("--tools", choices=("two", "all"), default="two", help=tools_help)
    parser.add_argument("--only", type=int, nargs="*", help="Run only these question ids.")
    args = parser.parse_args()

    questions = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    if args.only:
        questions = [question for question in questions if question["id"] in args.only]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{args.engine}-{args.model.replace(':', '_')}-{args.tools}-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"

    rows = []
    with spike_project() as (project_id, _root), out.open("w", encoding="utf-8") as log:
        cards = _offered(args.tools, project_id)
        ask = {"plain": _plain_engine, "graph": _graph_engine}[args.engine](args.model, cards, project_id)
        ask("Reply with OK.")  # loads the model, so the first question's time doesn't include loading it
        for question in questions:
            calls = []
            start = time.perf_counter()
            try:
                with patch.object(registry, "run", _recording_run(calls)):
                    answer = ask(question["question"])
            except Exception as error:  # a crash is a result too
                answer = f"CRASH {type(error).__name__}: {error}"
            seconds = round(time.perf_counter() - start, 1)
            row = {"id": question["id"], "kind": question["kind"], "seconds": seconds, "calls": calls, **_score(question, answer, calls)}
            if answer.startswith("CRASH"):
                row["failures"].append("crash")
            rows.append(row)
            log.write(json.dumps(row, ensure_ascii=False) + "\n")
            mark = "ok " if row["answer_ok"] else "BAD"
            print(f"{question['id']:>2} {mark} {seconds:5.1f}s {[call['tool'] for call in calls]} {row['failures']}")
    _summary(args, rows, out)


if __name__ == "__main__":
    main()
