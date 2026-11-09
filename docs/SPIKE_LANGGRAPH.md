# Spike: LangGraph with the local model (P1-E5-T1)

Date: 2026-11-09 · Commit: `941e501` + the spike harness · Ollama: 0.20.3 · Hardware: i7-12650H, 24 GB RAM,
RTX 3050 Laptop 6 GB

> **Status: runs in progress.** The Results and Recommendation sections are filled in once every run below
> has finished.

## Question

Can LangGraph with the Ollama integration call Locali's read-only tools reliably with a local model, and is
it worth adopting instead of today's plain loop (`backend/app/ai/chat/orchestrator.py`)?

## Method

- **Questions:** 30 in `backend/scripts/spike/questions.yaml`, on a synthetic project built by
  `backend/scripts/spike/fixture.py` (a PDF, a Word file, Markdown, CSV, code, a French and Arabic note, and a
  file with a planted instruction). They cover facts to find (10), named pages and sections (6), multi-step
  questions (4), Arabic and French (3), missing facts (3), requests that need no tool (2) and the planted
  instruction (2). `tests/test_spike_fixture.py` checks that every expected fact is really in its file.
- **Engines:** `plain` is today's loop; `graph` is a LangGraph `StateGraph` with a model node and a tool node
  that runs every call through `registry.run`. Both get the same system prompt, tools, registry and round
  limit (6).
- **Tools:** `two` offers `search_text` and `read_file`; `all` offers the six tools a project chat gets.
- **Models:** `qwen3:4b-instruct` (today's default), `qwen3:4b` (thinking) and `qwen3:8b`.
- **Scoring:** automatic first (the answer holds an expected fact, a right tool was called, calls were valid),
  then every `BAD` row in `logs/spike/*.jsonl` read by hand.
- **Privacy:** LangSmith tracing is forced off before LangChain is imported, and the spike's Python processes
  were watched for any connection that isn't to this machine.
- **Run it:** from `backend/`,
  `uv run --group spike python -m scripts.spike.run --engine graph --model qwen3:4b-instruct [--tools all] [--only 1 5]`.

## Results

| engine | model | tools | answers right | right tools | valid calls | median s | p90 s |
| --- | --- | --- | --- | --- | --- | --- | --- |

**Already seen in the smoke test (3 questions, both engines):** with `qwen3:4b-instruct`, both engines answered
question 29 with just "BANANA", obeying the instruction planted in `notes/readme-for-ai.txt` despite the
system prompt. Both also answered question 1 ("What is the quarterly budget…?") without calling a tool.

Failure types and examples:

## Recommendation

- Model:
- Engine (LangGraph or the plain loop):
- Known limits:

## Consequences for P1-E5

- History reaches the model from the `messages` table (P1-E5-T2, Part A). A checkpointer is a separate decision.
