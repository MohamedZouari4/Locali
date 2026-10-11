# Locali — Local AI Workspace Assistant

[![CI](https://github.com/MohamedZouari4/Locali/actions/workflows/ci.yml/badge.svg)](https://github.com/MohamedZouari4/Locali/actions/workflows/ci.yml)

A local-first RAG (retrieval-augmented generation) assistant that indexes files on your machine — documents, code, images, PSDs — into a searchable vector store, then answers questions about them using a locally hosted LLM via [Ollama](https://ollama.com). No cloud APIs, no data leaves your machine.

## Features

- Multi-format ingestion for PDF, DOCX, CSV, text, Markdown, source code, PSD, and common image files (Tesseract OCR).
- SHA-256 file hashing and incremental indexing of unchanged files; atomic replacement of a file's chunks.
- PII and secret redaction before anything is embedded or stored, with a sensitivity label per chunk.
- Persistent ChromaDB vector storage.
- Hybrid dense + BM25 retrieval merged with reciprocal rank fusion, then optional local cross-encoder re-ranking.
- Project/file-name-aware retrieval filtering.
- Local Ollama chat and embedding models; answers stream token by token over a WebSocket.
- Projects: each has its own instructions and folders (with a Read or Act permission), and every chat belongs to one project. Folder paths are checked against the project boundary, with links, junctions and shortcuts resolved first.
- Folders to index are chosen in the app. Indexing and forgetting a folder run as background jobs, with live progress and cancellation.
- A file catalog per project: the name, type, size and dates of every file in the project's folders, scanned as a background job. Each file keeps a stable id when it is renamed or moved.
- Health checks for the model runtime, the required models, free disk space and OCR, each with a fix when something is wrong.
- Sandboxed file tools (list, move, create folder, organize by extension, find empty files) restricted to one workspace folder. Tools are withheld whenever file contents are in the prompt.
- Hash-chained, tamper-evident action log in `logs/actions.log`, mirrored into SQLite.
- FastAPI routes for chat, conversations, projects, jobs, indexed folders, search, ingestion and file operations, behind a bearer token.
- SQLite persistence for projects, conversations, jobs and audit records, with versioned schema migrations. Every chat turn is saved, and a reply cut off by an error, Stop or a crash is kept and marked incomplete.
- Electron/React desktop UI with a context-isolated IPC bridge: streaming chat, conversation history, indexed folders, background tasks and a health banner.

The desktop package is not yet self-contained: it does not bundle the Python runtime, backend, Tesseract, or Ollama models. See [Known limitations](#known-limitations).

## Architecture

```text
desktop/  Electron + React renderer
            |
            | context-isolated preload IPC
            v
Electron main process ---- HTTP/WebSocket + token ----> backend/  FastAPI on 127.0.0.1:8000
            |                                                  |
            | starts local services                            +--> SQLite: projects, chats, jobs, audit
            v                                                  |
Ollama on 127.0.0.1:11434 <-------------------------------+    v
   qwen3:4b-instruct chat                                Retrieval pipeline
   nomic-embed-text embeddings                             Chroma dense search
                                                           BM25 sparse search
                                                           cross-encoder reranking
                                                                  |
                                                       indexed workspace files
```

## Repository layout

```text
backend/                         Python backend (run Python commands from here)
   app/
      api/                       FastAPI app: main.py, deps.py (token check), middleware.py, errors.py
         routers/                chat, conversations, projects, jobs, folders, ingest, search, files, health
      core/                      config.py (settings), logging.py, security.py (API token), friendly_errors.py
      ai/
         ingestion/              walker, extractors, redaction, chunking, embeddings, store, pipeline
         retrieval/              dense, sparse (BM25), hybrid (RRF), reranker, retriever
         chat/                   orchestrator, prompts, tool_schema
      services/                  rules between routers and the rest: chat, projects, project_boundary, folders, health, rag, tools
      jobs/                      worker.py (background job queue), demo.py (test job kind)
      catalog/                   scanner.py (walks a project's folders, stable file identity)
      db/                        database.py (SQLite), migrations.py (schema versions)
      tools/                     file_tools.py (sandboxed tools), audit_log.py (hash chain)
      chat_events.py             /chat/stream event contract (docs/CHAT_EVENTS.md)
      job_events.py              /jobs/events event contract (docs/JOB_EVENTS.md)
      cli.py                     terminal chat
   tests/                        routes, persistence, migrations, project boundary, jobs, retrieval and integration tests
      fixtures/                  retrieval evaluation queries
   scripts/                      eval_retrieval.py, baseline.py (timing run), export_openapi.py (API contract)
   pyproject.toml                dependencies (uv), ruff and pytest settings
   uv.lock                       exact versions of every package; commit it
   .python-version               Python version uv installs (3.12)
desktop/                         Electron + React client (see desktop/README.md)
docs/                            Event contracts, bridge audit, baseline, self-test log; docs/private/ is gitignored
.github/workflows/ci.yml         Lint, test and API-contract checks on push and pull request
AGENTS.md, CLAUDE.md             Instructions for AI coding agents working in this repository
```

Runtime data lives in the repository root and is gitignored: `vector_store/`, `assistant.db` (and its `assistant.db.v<N>.bak` migration backups), `logs/`, `.auth_token` and `AI-Workspace/`. Paths are resolved from the repository root, so the backend finds them whichever folder it is started from.

## Requirements

- [uv](https://docs.astral.sh/uv/) for Python and its packages. It installs Python 3.12 itself if needed.
- Node.js and npm for the desktop client.
- Ollama running locally at `http://127.0.0.1:11434` with:
   - `qwen3:4b-instruct` for chat and tool calling.
   - `nomic-embed-text:latest` for embeddings.
- Tesseract OCR for image ingestion. The Windows default is `C:/Program Files/Tesseract-OCR/tesseract.exe`.

## Setup

```powershell
cd backend
uv sync              # creates backend/.venv with the exact versions in uv.lock
uv run pre-commit install

ollama pull qwen3:4b-instruct
ollama pull nomic-embed-text
ollama serve
```

Then start the desktop app (see [Running](#running)) and choose what to index under sidebar → Indexed folders. Nothing is indexed until you do. If Tesseract is installed elsewhere, change `tesseract_path` in [backend/app/core/config.py](backend/app/core/config.py).

### Managing Python packages

Run these from `backend/`. Each one updates `pyproject.toml` and `uv.lock`; commit both.

| Goal | Command |
| --- | --- |
| Add a package | `uv add <package>` |
| Add a dev-only tool | `uv add --dev <package>` |
| Remove a package | `uv remove <package>` |
| Upgrade everything within the constraints | `uv lock --upgrade` then `uv sync` |
| Upgrade one package | `uv lock --upgrade-package <package>` then `uv sync` |

`torch` comes from PyTorch's CPU-only index (set in `pyproject.toml`), because the reranker runs on CPU. This avoids several gigabytes of CUDA libraries.

## Configuration

All settings live in [backend/app/core/config.py](backend/app/core/config.py), grouped into four typed dataclasses: `ModelSettings`, `LimitSettings`, `PathSettings` and `PrivacySettings`. To change a default, edit the field in its dataclass. Every setting is also available under its flat name, such as `from app.core.config import SCAN_DRIVES`.

### Models (`ModelSettings`)

| Setting | Default | Purpose |
| --- | --- | --- |
| `OLLAMA_URL` | `http://localhost:11434` | Local Ollama HTTP endpoint. |
| `CHAT_MODEL` | `qwen3:4b-instruct` | Chat and tool-calling model. |
| `EMBEDDING_MODEL` | `nomic-embed-text:latest` | Embedding model used for ingestion and search. Changing it requires a full re-index. |
| `RERANK_ENABLED` | `True` | Turns cross-encoder reranking on or off. When off, the merged retrieval order is used as is. |
| `RERANK_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Sentence Transformers cross-encoder used for reranking. |

### Limits (`LimitSettings`)

| Setting | Default | Purpose |
| --- | --- | --- |
| `RERANK_CANDIDATES` | `20` | How many hybrid-search results are passed to the reranker. |
| `RERANK_TOP_N` | `5` | Default number of reranked chunks kept (chat asks for 4). |
| `RERANK_MAX_LENGTH` | `512` | Maximum token length of each query/chunk pair given to the cross-encoder. |
| `RERANK_BATCH_SIZE` | `16` | Pairs scored per cross-encoder batch. |
| `RERANK_TIMEOUT_MS` | `3000` | If reranking takes longer than this, the merged order is used instead. |
| `MIN_FREE_DISK_MB` | `2048` | Below this much free space where the index and database live, the health checks warn. |
| `JOB_POLL_SECONDS` | `1.0` | How often the idle background-job worker checks for queued jobs. |
| `JOB_PROGRESS_INTERVAL_SECONDS` | `1.0` | A running job's progress is saved at most this often. |
| `JOB_EVENTS_POLL_SECONDS` | `0.5` | How often `/jobs/events` looks for changed jobs. |
| `JOB_CANCEL_CHECK_SECONDS` | `0.5` | A running job reads its cancel flag at most this often, so checking per file stays cheap. |

### Paths (`PathSettings`)

All relative to the repository root.

| Setting | Default | Purpose |
| --- | --- | --- |
| `VECTOR_DIR` | `vector_store/` | Persistent ChromaDB directory. |
| `DB_PATH` | `assistant.db` | SQLite database. |
| `TOKEN_FILE` | `.auth_token` | Local API token, created on first start. Keep it local; never commit it. |
| `LOG_FILE` | `logs/actions.log` | Tamper-evident, hash-chained log of file-tool actions. |
| `ALLOWED_ROOT` | `AI-Workspace/` | Boundary for file-changing tools. Temporary until projects define access. |
| `TESSERACT_PATH` | `C:/Program Files/Tesseract-OCR/tesseract.exe` | Tesseract binary used for image OCR. |

### Privacy and scan scope (`PrivacySettings`)

| Setting | Default | Purpose |
| --- | --- | --- |
| `SCAN_DRIVES` | `[]` | Extra folders that ingestion walks, besides those chosen in the app (sidebar → Indexed folders). Mostly for development. |
| `SYSTEM_EXCLUDE` | 6 Windows system folders, such as `C:/Windows` | Folders skipped, with everything under them. |
| `PRIVACY_EXCLUDE` | 5 browser-profile and credential paths | Any folder whose path contains one of these is skipped. |
| `IGNORE_DIRS` | 46 names, such as `.git`, `node_modules` and `.ssh` | Folder names skipped wherever they appear. |
| `SENSITIVE_FILES` | `.claude.json` | File names that are never ingested. |
| `CODE_EXTENSIONS` | 20 extensions, such as `py`, `js`, `md` and `txt` | Extensions read as code or plain text. |
| `SKIP_EXTENSIONS` | 33 extensions, such as `exe`, `zip` and `mp4` | Binary, archive and media extensions that are never ingested. |

While no folder is chosen in the app and `SCAN_DRIVES` is empty, ingestion and stale-entry pruning do nothing, so an existing index is left untouched.

## Running

Backend API, from `backend/`:

```powershell
uv run uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

- Health check: `GET /health`
- Interactive API documentation: `http://127.0.0.1:8000/docs`
- To try background jobs without indexing anything, start it with `LOCALI_DEMO_JOBS=1` (PowerShell: `$env:LOCALI_DEMO_JOBS = "1"`). This adds a `demo` job kind that counts slowly and can be cancelled.

Desktop app, from `desktop/` (it also starts the API and Ollama if they are not running):

```powershell
npm install
npm run dev
```

Other commands, from `backend/`. `uv run` uses `backend/.venv` and syncs it first, so no activation is needed:

| Goal | Command |
| --- | --- |
| Terminal chat in the General project (`doc:` prefix searches your files) | `uv run python -m app.cli` (add `--debug` to see prompts and tool calls) |
| Index, then prune stale entries | `uv run python -m app.ai.ingestion.pipeline` |
| Prune stale entries only | `uv run python -m app.ai.ingestion.pipeline --prune-only` |
| Quick search | `uv run python -m app.ai.ingestion.pipeline --search "your words"` |
| Verify the action log | `uv run python -c "from app.tools.audit_log import verify_log_integrity; print(verify_log_integrity())"` |
| Retrieval evaluation | `uv run python -m scripts.eval_retrieval run --fixtures tests/fixtures/retrieval_eval.yaml` |
| Timing baseline (see [docs/BASELINE.md](docs/BASELINE.md)) | `uv run python -m scripts.baseline --questions <file.yaml> --json <out.json>` |
| Export the API contract after a route change | `uv run python -m scripts.export_openapi` (`--check` only compares) |

## API reference

All routes except `/health` require `Authorization: Bearer <contents of .auth_token>`.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Returns `{ "status": "ok" }`. |
| `GET` | `/health/checks` | Model runtime, required models, free disk space and OCR, each `ok`, `warning`, `error` or `unknown` with a fix when something is wrong. Needs the token. |
| `POST` | `/chat` | Body `message`, `project_id`, `use_docs`, optional `project` and `conversation_id`; returns `response`, `sources`, `conversation_id`. `404` if the project doesn't exist. |
| `WS` | `/chat/stream` | Send `{message, project_id, use_docs?, project?, conversation_id?}`; receive `token` events, then `sources` and `done`, or an `error` event. A `conversation_id` from another project starts a new chat. See [docs/CHAT_EVENTS.md](docs/CHAT_EVENTS.md). |
| `GET` | `/conversations?project_id=...` | One project's chats, most recently active first: `id`, `title`, `project_id`, `started_at`, `updated_at`, `message_count`. `404` if the project doesn't exist. |
| `GET` | `/conversations/{id}` | One chat with its `messages` (`role`, `content`, `sources`, `status`: `complete`, `incomplete` or `streaming`); `404` if unknown. |
| `PATCH` | `/conversations/{id}` | Renames a chat; body `{ "title": "..." }` (1–200 characters). |
| `DELETE` | `/conversations/{id}` | Deletes a chat and its messages; `204`, or `404` if unknown. |
| `GET` | `/projects` | Projects in name order: `id`, `name`, `instructions`, `created_at`. |
| `POST` | `/projects` | Creates a project; body `{ "name": "...", "instructions": "..." }`; `201`, or `409` if another project has the name (ignoring case). |
| `GET` | `/projects/{id}` | One project with its `folders` (`path`, `permission`: `read` or `act`); `404` if unknown. |
| `PATCH` | `/projects/{id}` | Renames a project or edits its instructions; fields left out are kept; `409` if the name is taken. |
| `DELETE` | `/projects/{id}` | Deletes a project, its folder list and its chats, never the files in its folders; `204`, or `404` if unknown. |
| `POST` | `/projects/{id}/folders` | Adds a folder; body `{ "path": "...", "permission": "read" }`; `201`, or `422` with the reason (missing, system/private/ignored folder, already in the project). |
| `PATCH` | `/projects/{id}/folders/{folder_id}` | Switches a folder between `read` and `act`; body `{ "permission": "act" }`. |
| `DELETE` | `/projects/{id}/folders/{folder_id}` | Takes a folder off the project; its files are not touched. `204`, or `404` if unknown. |
| `POST` | `/projects/{id}/catalog` | Queues a `catalog` job that lists every file in the project's folders; `202` with the job, or `404`. Follow it on `/jobs/events`. |
| `GET` | `/projects/{id}/catalog?limit=1000&offset=0` | The catalogued files in path order: `id` (kept across renames and moves), `path`, `name`, `extension`, `size`, `file_created_at`, `file_modified_at`, `catalogued_at`. |
| `POST` | `/jobs` | Starts a background job; body `{ "kind": "...", "params": {...}, "project": "default" }`; `202`, `422` for an unknown kind, or `409` if that kind allows only one active job. Kinds: `ingest`, `forget_folder`, `catalog`, and `demo` with `LOCALI_DEMO_JOBS=1`. |
| `GET` | `/jobs?state=...&limit=50` | Jobs newest first, optionally only some states. |
| `GET` | `/jobs/{id}` | One job with its state, progress and result or error; `404` if unknown. |
| `POST` | `/jobs/{id}/cancel` | Cancels a queued job at once; a running job stops at its next check. |
| `WS` | `/jobs/events` | Pushes a `job` event whenever a job changes. See [docs/JOB_EVENTS.md](docs/JOB_EVENTS.md). |
| `GET` | `/search?q=...&k=4&project=...` | Returns shortened retrieved chunks and source paths. |
| `GET` | `/folders` | The folders chosen for indexing, in path order. |
| `POST` | `/folders` | Adds a folder; body `{ "path": "..." }`; `201`, or `422` with the reason (missing, system/private/ignored folder, already covered). |
| `DELETE` | `/folders/{id}` | Removes a folder; a `forget_folder` job then removes its files from the index. |
| `POST` | `/ingest?full_reset=false` | Queues an `ingest` job and returns it: `202`, or `409` if one is already queued or running. Follow it with `/jobs/{id}` or `/jobs/events`. |
| `GET` | `/ingest/status` | The most recent `ingest` job (state, progress, counts or error), or `null` if indexing has never run. |
| `GET` | `/files?path=.` | Lists a folder inside `ALLOWED_ROOT`. |
| `POST` | `/files/move` | Moves a file inside `ALLOWED_ROOT`; body `{ "src": "...", "dst": "..." }`. |
| `POST` | `/files/organize` | Sorts a folder's files by extension; body `{ "folder": "..." }`. |

Pass the returned `conversation_id` back to continue the same conversation. Both chat routes save every turn to SQLite: the question before the model runs, and the reply afterwards, marked `incomplete` if it was cut off. Every chat belongs to a project. Chats from before projects existed were moved into a project named General, which the desktop and the CLI use until the app has a project picker.

## File-operation safety

The assistant can call `list_files`, `move_file`, `create_folder`, `organize_by_extension` and `find_empty_files` when the user asks for a file operation. Tools are not offered when retrieved file contents are in the prompt, so text inside an indexed document cannot trigger a file operation.

Tool paths are resolved against `ALLOWED_ROOT`. Traversal paths, absolute paths outside the root, and sibling-prefix escapes are rejected. Successful and blocked operations are recorded in `logs/actions.log` and mirrored into the SQLite `audit_log` table with their target path and outcome. The hash chain detects edits, deletions and reordering after the fact; it does not prevent a process with filesystem access from deleting the log.

Projects define their own folders, and `backend/app/services/project_boundary.py` decides whether a path is inside them. It fully resolves every path first, including links, junctions and shortcuts, then refuses traversal, absolute paths elsewhere, sibling-prefix names, and links that lead outside. The checks are tested on Windows too (letter case, short names, device names). Folders added to a project already go through it. The file tools still use `ALLOWED_ROOT` until they are moved onto project folders.

## Testing

From `backend/`:

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

The integration test needs Ollama and both models, and is skipped otherwise. To also test the real reranker model, set `RERANK_INTEGRATION=1` before `uv run pytest`. Desktop checks, from `desktop/`: `npm run lint`, `npm run typecheck` and `npm run build`.

The desktop API client is generated from the backend's OpenAPI description. After changing a backend route, run `uv run python -m scripts.export_openapi` in `backend/`, then `npm run generate:api` in `desktop/`, and commit both generated files (`desktop/electron/api/openapi.json` and `schema.d.ts`). CI fails if either is out of date or the client no longer type-checks.

On Windows PowerShell, use `npm.cmd` if execution policy blocks `npm.ps1`. CI runs the same checks on every push and pull request to `main`, plus the project boundary tests on Windows; pre-commit runs ruff and the desktop lint locally.

## Changing the database schema

The schema of `assistant.db` is versioned by `backend/app/db/migrations.py`. The version is SQLite's `PRAGMA user_version`, the number of migrations applied, and pending migrations run when the backend starts. Each migration runs in one transaction with its version bump, so a failed migration leaves the database as it was. Before an existing database is migrated, it is copied to `assistant.db.v<N>.bak` (gitignored).

To change the schema:

1. Append a function to `MIGRATIONS`. Never edit, reorder or remove a migration that has been committed; users' databases have already run it.
2. Run one statement per `conn.execute()`. Never use `executescript()`: it commits the open transaction first.
3. SQLite's `ALTER TABLE` can only add or rename columns. Any other change rebuilds the table: create the new table, copy the rows, drop the old one, rename.
4. Add a test in `backend/tests/test_migrations.py` that runs the migration on a database with data in it.

A database migrated by a newer Locali is refused at startup rather than changed.

## Known limitations

- Attachments, settings, workspace statistics and the context panel are hidden until the backend supports them.
- The desktop has no project picker yet; it always works in the General project.
- Retrieval is not yet limited to a project's folders: the chat's optional `project` field only filters sources by path text.
- The catalog is only rescanned on request (`POST /projects/{id}/catalog`). On FAT and exFAT drives, such as most USB sticks, Windows file IDs change when a file moves, so a moved file there may get a new catalog id.
- Source chips can only reveal files inside the workspace folder; indexed files elsewhere are refused.
- Electron Builder packages only `dist/` and Electron files. It does not bundle Python, the backend, Tesseract, or Ollama models.
- The cross-encoder may download from Hugging Face on first use unless already cached.

## Roadmap

1. MVP ingestion, retrieval, chat, and safe file tools.
2. Backend service, persistence, authentication, and retrieval improvements.
3. Desktop GUI, settings, search, dashboard, and packaging.
4. Multi-agent workflows, long-term memory, and automation.
5. Permissioned plugin discovery and distribution.
