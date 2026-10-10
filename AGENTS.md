# AGENTS.md

Instructions for AI coding agents working in this repository. The [README](README.md) is the full
reference for settings, routes and commands; this file covers what an agent needs to work safely here.

## What Locali is

A local-first RAG assistant. It indexes files on the user's machine into ChromaDB + BM25 and answers
questions with a local Ollama model. **Nothing leaves the machine**: never add a cloud API, telemetry,
or a dependency that phones home.

- `backend/`: Python 3.12, FastAPI on `127.0.0.1:8000`, SQLite (`assistant.db`), ChromaDB, Ollama
  (`qwen3:4b` chat, `nomic-embed-text` embeddings), a cross-encoder reranker on CPU.
- `desktop/`: Electron + React (Vite). The renderer only talks to the preload bridge
  (`window.localiAPI`); `electron/main.cjs` makes every API call and holds the token.
- `docs/`: tracked design docs (chat/job event contracts, bridge audit, baseline). `docs/private/` is gitignored.

Backend layering: `api/routers` → `services` → `ai/` (ingestion, retrieval, chat), `db/`, `tools/`.
Routers stay thin; checks and rules live in services.

## Commands

Python commands run from `backend/` through uv. Don't activate the venv or use pip.

```powershell
# backend/
uv sync                                   # install exact versions from uv.lock
uv run uvicorn app.api.main:app --host 127.0.0.1 --port 8000
uv run ruff check . ; uv run ruff format --check .
uv run pytest -q                          # integration test skips without Ollama
uv run pytest -q tests/test_project_boundary.py
uv run python -m scripts.export_openapi   # after any route change

# desktop/   (use npm.cmd if PowerShell blocks npm.ps1)
npm run dev                               # Vite + Electron; also starts the API and Ollama
npm run generate:api                      # after export_openapi
npm run lint ; npm run typecheck ; npm run build
```

Add packages with `uv add <pkg>` (or `uv add --dev`) and commit `pyproject.toml` and `uv.lock` together.
`torch` comes from the CPU-only index; keep it that way.

## Rules that CI enforces

CI (`.github/workflows/ci.yml`) runs on every push to `main`. Before saying a change is done, run the
same checks:

1. `ruff check` and `ruff format --check` pass (line length 140, rules E, F, I, UP).
2. `pytest -q` passes.
3. **API contract is in sync.** Any change to a backend route or its models requires
   `uv run python -m scripts.export_openapi` in `backend/`, then `npm run generate:api` in `desktop/`.
   Commit both `desktop/electron/api/openapi.json` and `schema.d.ts`. CI fails if either is stale or
   `npm run typecheck` breaks.
4. Desktop `npm run lint` passes. Stylelint forbids raw color values: use the tokens in
   `desktop/src/styles/tokens/` (primitives → semantic → spacing).
5. The boundary tests also run on Windows (junctions, letter case, short names, device names).

## Code conventions

- **Every source file starts with a header comment** (a Python docstring, or `//` lines in JS) that says
  what the file does and any non-obvious rules. Keep it accurate when you change the file.
- Match the surrounding code's style: plain functions, small services, few abstractions. Comments explain
  *why*, in full sentences.
- Settings live only in `backend/app/core/config.py`, in the typed dataclasses `ModelSettings`,
  `LimitSettings`, `PathSettings` and `PrivacySettings`, and each one is also exported under a flat name.
  A new setting goes in its dataclass, gets a flat alias, and gets a row in the README table.
- Paths for runtime data are resolved from the repository root, not the working directory.
- Prefer the standard library and existing dependencies. Justify any new dependency.

## Database schema

`backend/app/db/migrations.py` versions the schema with `PRAGMA user_version`.

- To change the schema, append a new migration to `MIGRATIONS`. **Never edit, reorder or remove a committed migration.**
- Run one statement per `conn.execute()`; never use `executescript()`.
- SQLite `ALTER TABLE` only adds or renames columns. For any other change, rebuild the table.
- Add a test in `tests/test_migrations.py` that migrates a database with data already in it.

## Security and privacy (do not weaken)

- **Project boundary** (`services/project_boundary.py`): every path is fully resolved, including links,
  junctions and shortcuts, before it is checked against the project's folders. Traversal, absolute paths,
  sibling-prefix names and links that point outside are all refused. Any change here needs a test in
  `tests/test_project_boundary.py`.
- File tools are withheld whenever retrieved file contents are in the prompt, so a document can never
  trigger a file action. Keep it that way.
- Every file action, whether it succeeds or is blocked, goes through the hash-chained audit log
  (`tools/audit_log.py`).
- Redaction runs before anything is embedded or stored.
- All routes except `/health` require the bearer token. The desktop renderer never sees the token.
- Never commit runtime data: `assistant.db*`, `.auth_token`, `vector_store/`, `logs/`, `data/`,
  `storage/`, `AI-Workspace/`, `docs/private/`. Real user paths and file contents don't belong in tests,
  fixtures or docs.

## Streaming and saving contracts

- Chat streams over `WS /chat/stream`, using the versioned events in `app/chat_events.py` (documented in
  `docs/CHAT_EVENTS.md`). If you change an event, update the doc and the version.
- The user message is saved before the agent runs. The reply is always saved, and is marked `incomplete`
  if it was interrupted. Don't move saving back out of the gateway.
- Long work (ingestion, forgetting a folder) runs as a background job (`app/jobs/`), with progress over
  `WS /jobs/events` (`docs/JOB_EVENTS.md`). Routes return `202` with the job and never block.

## Work tracking

Work follows tickets with IDs like `P1-E1-T4` (Phase, Epic, Task), each with steps and acceptance
criteria. Do one ticket at a time, meet every acceptance criterion, and name the ticket in test
docstrings where it helps. When behavior, routes or settings change, update the README in the same change.

## Commits

Use short, imperative subjects in plain English that say what the change does, for example
`Add the project boundary check`. At most 2–3 short body lines. Don't push or commit unless asked.
