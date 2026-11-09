# Spike: LangGraph with the local model (P1-E5-T1)

Date: 2026-11-09 · Commits: `27532a9` (harness), runs on `8662383` · Ollama: 0.20.3 · Hardware: i7-12650H,
24 GB RAM, RTX 3050 Laptop 6 GB

> **Decided 2026-11-09** (Notion Decision Log): keep today's plain loop and `qwen3:4b-instruct` for Phase 1, and
> revisit LangGraph for Phase 2 approvals. The fixes the spike pointed to were made the same day; their effect
> is under "After the fixes" below.

## Question

Can LangGraph with the Ollama integration call Locali's read-only tools reliably with a local model, and is
it worth adopting instead of today's plain loop (`backend/app/ai/chat/orchestrator.py`)?

## Answer in short

LangGraph calls the tools as well as today's loop does, and no better: on the same model, both scored the same.
What limits Locali today is the model's habits and two gaps in Locali itself (how `search_text` matches words,
and a prompt that doesn't push the model to look in the files), not the engine.

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
- **Models:** `qwen3:4b-instruct` (today's default), `qwen3:4b` (thinking) and `qwen3:8b` (thinking).
- **Scoring:** automatic first (the answer holds an expected fact, a right tool was called, calls were valid),
  then every `BAD` row in `logs/spike/*.jsonl` read by hand.
- **Privacy:** LangSmith tracing is forced off before LangChain is imported, and the spike's Python processes
  were watched for any connection that isn't to this machine.
- **Run it:** from `backend/`,
  `uv run --group spike python -m scripts.spike.run --engine graph --model qwen3:4b-instruct [--tools all] [--only 1 5]`.

## Results

One run each; nothing fixes the sampling, so differences of 2 or 3 answers are noise.

| engine | model | tools | answers right | right tools | valid calls | median s | p90 s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| plain | qwen3:4b-instruct | two | 11/30 | 16/30 | 13/14 | 5.0 | 8.6 |
| graph | qwen3:4b-instruct | two | 11/30 | 16/30 | 13/14 | 2.1 | 3.9 |
| plain | qwen3:4b-instruct | all | 15/30 | 18/30 | 29/30 | 6.9 | 15.0 |
| graph | qwen3:4b-instruct | all | 13/30 | 18/30 | 28/29 | 2.7 | 10.6 |
| graph | qwen3:4b (thinking) | two | 21/30 | 28/30 | 28/29 | 38.8 | 101.0 |
| graph | qwen3:8b (thinking) | two | 20/30 | 29/30 | 29/30 | 63.6 | 97.0 |
| graph | qwen3:8b (thinking) | all | 18/30 | 26/30 | 45/53 | 88.1 | 222.2 |

The `plain` runs took about twice as long per answer (median 5–7 s against 2–3 s), also in the smoke test
before the model download started. The cause wasn't investigated (the two may send different request options
to Ollama), so check it before reading it as an engine difference. No spike
process connected anywhere but this machine (603 samples over about 12 minutes).

## What went wrong, read by hand

| Failure | Where | What happened |
| --- | --- | --- |
| **No tool called** | `qwen3:4b-instruct`: 10 of 10 fact questions with two tools | It answered "I don't have access to any project files" without searching. The thinking models almost always searched. |
| **Search found nothing that is there** | every model | `search_text` needs every word in the same page or part, and matches whole words only. Checked on the fixture: "Greenhouse budget" finds nothing (the words are on pages 1 and 2), "risk" doesn't match "Risks", "launch date" and "dashboard owner" find nothing, and "الحرارة" doesn't match "للحرارة". The model then said the fact wasn't in the files. |
| **Obeyed the planted instruction** | `qwen3:4b-instruct`: 2 of 2; `qwen3:8b` with six tools: 2 of 2 | Replied only "BANANA" after reading `notes/readme-for-ai.txt`. The thinking models with two tools reported the instruction instead. |
| **Empty answer** | `qwen3:8b`: 4 questions; `qwen3:4b`: 3 | The final message had no text; the reasoning went into the thinking field and no answer followed. |
| **Tool call as text** | `qwen3:4b`: question 15 | It wrote `{"name": "search_text", …}` as the answer instead of making the call. |
| **Wrong tool** | `qwen3:4b-instruct` with six tools | It looked for `config.ini` or `pump.py` with `find_files`, found the file, and answered from the name, not the content. |
| **Invented arguments** | `qwen3:8b` with six tools | It passed `path` to `search_text` three times, then ran out of rounds. |

Scoring was too strict in one place only: question 13 failed because the model typed the file name wrong
(`meeting-2026-10--02.md`), which is a real failure, not a scorer error. No question was re-scored.

## After the fixes

The same 30 questions on the default model with today's loop (the `plain` engine routes each question as the chat
service does). One run each.

| Stage | Two tools | Six tools | Facts to find | Arabic, French | Planted instruction | Median s (two / six) |
| --- | --- | --- | --- | --- | --- | --- |
| Before | 11/30 | 15/30 | 0/10 | 1/3 | 0/2 | 5.0 / 6.9 |
| Looser `search_text` + prompt rule | 15/30 | 16/30 | 1/10 | 2/3 | 1/2 · 0/2 | 6.7 / 6.9 |
| + router, search before answering, question repeated after file text | 19/30 | 20/30 | 7/10 | 3/3 | 1/2 · 2/2 | 12.1 / 37.2 |

`search_text` now matches word beginnings, falls back to pages with some of the words, and matches Arabic words
with a prefix (P1-E4-T7). A project question or multi-step task gets a `search_text` of the question before the
model's first turn, and the question is repeated after file text (P1-E5-T3 wiring, P1-E5-T9).

Still wrong, read by hand:

- **Named reads got worse (2/6).** "Read page 3 of q3-report.pdf" is searched first, and the model answers from the
  snippets instead of calling `read_file`. Skip the search when the question names a file and a page or section.
- **Snippets start at common words.** The question's own words include "the", so a snippet reads "We move **the**
  launch to 15…" and cuts off the fact. Drop common words from the search-first query.
- **Slower.** The median rose to 12 s with two tools and 37 s with six: about ten snippets now reach the prompt,
  plus the router call. This needs measuring before the change is used day to day.
- **Router misses.** Three fact questions ("Which sensor fails in heavy rain?" and two more) were routed as
  general chat, so they weren't searched.

## Recommendation

- **Engine: keep today's plain loop for Phase 1.** LangGraph scored the same, and it brings about 20 packages
  (LangChain core, LangSmith client) that must be kept from phoning home. What it would add is checkpoints and
  pausing a run for a person's approval; revisit it for Phase 2 approvals (P2-E2), with this harness.
- **Model: keep `qwen3:4b-instruct` as the default**, and fix Locali first. A thinking model doubles the
  answers it gets right (21/30) but takes about 39 s per answer, and `qwen3:8b` is no better than the 4B
  thinking model while slower still, so a larger model isn't worth it on this hardware.
- **Fix before choosing again, then re-run this spike:**
  1. `search_text`: rank pages that match some of the words, not only all of them, and match word beginnings
     ("risk" → "Risks"), including after Arabic one-letter prefixes (ل، ب، و، ف، ك).
  2. The system prompt: questions about the user's projects, notes, reports or code are about their files, so
     search before saying the answer isn't there.
  3. P1-E5-T9: label file text as data. The default model obeyed the planted instruction every time.
- **Worth trying after those fixes:** `qwen3:4b` with thinking as an opt-in "careful" mode for hard questions.

## Known limits of this spike

- One run per configuration, 30 questions, one synthetic project in English with three Arabic and French
  questions; real projects are larger and messier.
- The thinking models ran only on the graph engine; with the engines equal on the instruct model, that is
  unlikely to change the picture.
- Thinking was left at Ollama's default; turning it off for `qwen3:8b` was not tried.

## Consequences for P1-E5

- History reaches the model from the `messages` table (P1-E5-T2, Part A). With the plain loop kept, P1-E5-T2
  needs no checkpointer for Phase 1: the saved messages already survive a restart.
- The router (P1-E5-T3) is a plain function, so it works in today's loop as well as in a graph.
- New tickets suggested: better `search_text` matching (partial matches, word beginnings, Arabic prefixes), and a
  prompt rule to search the files before saying something isn't there.
