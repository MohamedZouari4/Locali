# Local AI Workspace Assistant

A local-first RAG (retrieval-augmented generation) pipeline that indexes files on your machine — documents, code, images, PSDs — into a searchable vector store, then answers questions about them using a locally-hosted LLM via [Ollama](https://ollama.com). No cloud APIs, no data leaves your machine.

The full software design document and development backlog are kept in a local `DOCS/` folder, which is gitignored (not part of this repo).

## Features
## Current status

The project is migrating from the original flat command-line prototype to a packaged Python application with a FastAPI service and an Electron/React desktop client.

The current implementation includes:

- Multi-format ingestion for PDF, DOCX, CSV, text, Markdown, source code, PSD, and common image files.
- Tesseract OCR for supported images.
- SHA-256 file hashing and incremental indexing of unchanged files.
- Persistent ChromaDB vector storage.
- Hybrid dense plus BM25 retrieval.
- Optional local cross-encoder re-ranking through Sentence Transformers.
- Project/file-name-aware retrieval filtering.
- Local Ollama chat and embedding models.
- Sandboxed tools for listing, moving, creating folders, organizing by extension, and finding empty files.
- `ALLOWED_ROOT` path validation before file operations.
- Hash-chained action logging in `logs/actions.log`.
- FastAPI routes for chat, search, ingestion, and file operations.
- SQLite persistence for conversations, messages, and audit records.
- Bearer-token authentication for the local API and chat WebSocket.
- Electron/React desktop UI with a context-isolated IPC bridge.

The desktop package is not yet self-contained: it does not bundle the Python runtime, backend, Tesseract, or Ollama models. See [Known limitations](#known-limitations).

## Architecture

```text
Electron + React renderer
            |
            | context-isolated preload IPC
            v
Electron main process ---- HTTP/WebSocket ----> FastAPI on 127.0.0.1:8000
            |                                          |
            | starts local services                    +--> SQLite conversations/audit
            v                                          |
Ollama on 127.0.0.1:11434 <-----------------------+
   qwen3:4b chat                                    v
   nomic-embed-text embeddings              Retrieval pipeline
                                                                   Chroma dense search
                                                                   BM25 sparse search
                                                                   cross-encoder reranking
                                                                               |
                                                                   indexed workspace files
```

## Project layout

```text
app/
   api.py                       FastAPI application
   config.py                    Models, paths, scan scope, exclusions
   database.py                  SQLite persistence
   AI/
      ingest.py                  Extraction, redaction, chunking, indexing
      orchestrator.py            RAG prompts and tool-calling loop
      retriever.py               Retrieval facade
      retrieval/                 Dense, sparse, hybrid, and reranking modules
   routers/                     Chat, search, ingest, and file routes
   services/                    Auth, persistence, logging, and API services
   tool/tools.py                Sandboxed file operations and action log
locali-desktop/
   electron/                    Electron main and preload processes
   src/                         React renderer and chat UI
   package.json                 Desktop scripts and dependencies
tests/                         Unit, persistence, integration, and reranking tests
fixtures/                      Retrieval evaluation fixtures
DOCS/                          Backlog and design documents
PROJECT_REVIEW.md              Engineering review and migration risks
requirements.txt               Python dependencies
```

The former root-level modules such as `config.py`, `ingest.py`, `retriever.py`, `orchestrator.py`, `tools.py`, and `main.py` have been moved into the `app/` package. Imports should use paths such as `app.config`, `app.AI.ingest`, and `app.tool.tools`.

## Requirements

- Python 3.11 or newer.
- Node.js and npm for the desktop client.
- Ollama running locally at `http://127.0.0.1:11434`.
- Ollama models:
   - `qwen3:4b` for chat and tool calling.
   - `nomic-embed-text:latest` for embeddings.
- Tesseract OCR for image ingestion. The Windows default is `C:/Program Files/Tesseract-OCR/tesseract.exe`.

Python dependencies are listed in [requirements.txt](requirements.txt), including FastAPI, Uvicorn, ChromaDB, document parsers, `rank_bm25`, and `sentence-transformers`.

## Python setup

From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Install Ollama, then pull the required models:

```powershell
ollama pull qwen3:4b
ollama pull nomic-embed-text
ollama serve
```

If Tesseract is installed elsewhere, update `TESSRACT_PATH` in [app/config.py](app/config.py).

## Configuration

The main configuration is in [app/config.py](app/config.py):

| Setting | Purpose |
| --- | --- |
| `OLLAMA_URL` | Local Ollama HTTP endpoint. |
| `CHAT_MODEL` | Chat and tool-calling model. |
| `EMBEDDING_MODEL` | Embedding model. |
| `RERANK_ENABLED` | Enables cross-encoder reranking behavior. |
| `RERANK_MODEL` | Sentence Transformers cross-encoder name. |
| `RERANK_CANDIDATES` / `RERANK_TOP_N` | Candidate and final result counts. |
| `SCAN_DRIVES` | Roots scanned by ingestion. The current default includes `D:/` and common user folders. |
| `VECTOR_DIR` | Persistent ChromaDB directory. |
| `ALLOWED_ROOT` | Workspace boundary for file tools; defaults to `app/AI-Workspace`. |
| `SYSTEM_EXCLUDE` / `PRIVACY_EXCLUDE` | Absolute paths excluded from scans. |
| `IGNORE_DIRS` | Directory names skipped during recursive walking. |
| `SENSITIVE_FILES` / `SKIP_EXTENSIONS` | Files and extensions never ingested. |

Review `SCAN_DRIVES` before the first ingest. The default includes a whole drive and can scan more data than intended. `ALLOWED_ROOT` is a separate safety boundary for file-changing tools and should point to a dedicated workspace folder.

On first startup, [app/services/auth.py](app/services/auth.py) creates `.auth_token`. Keep this file local and do not commit it.

## Running the backend

Start the API from the repository root:

```powershell
.venv\Scripts\Activate.ps1
python -m uvicorn app.api:app --host 127.0.0.1 --port 8000
```

The API is available at `http://127.0.0.1:8000`.

- Health check: `GET /health`
- Interactive API documentation: `http://127.0.0.1:8000/docs`
- OpenAPI schema: `http://127.0.0.1:8000/openapi.json`

All routes except `/health` require:

```text
Authorization: Bearer <contents of .auth_token>
```

## Ingestion and retrieval

The ingestion pipeline:

1. Walks every root in `SCAN_DRIVES`.
2. Skips system, privacy, cache, sensitive, binary, archive, media, and oversized files according to configuration.
3. Extracts text from supported formats. PSD ingestion includes layer names and text layers; image ingestion uses Tesseract OCR.
4. Detects common PII and secret-like values and redacts them before embedding.
5. Splits content into sections and chunks of approximately 4,000 characters.
6. Embeds chunks through Ollama and stores metadata in ChromaDB.
7. Uses file hashes and modification metadata to skip unchanged files.

Retrieval combines dense vector results and BM25 keyword results, merges them with reciprocal-rank fusion, and re-ranks candidates with a local cross-encoder when configured. Queries can pass a `project` string to prefer sources whose path contains that value.

Trigger ingestion through the API:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/ingest" `
   -H "Authorization: Bearer <token>"
```

Reset the collection before ingesting with `POST /ingest?full_reset=true`.

## API reference

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Returns `{ "status": "ok" }`. |
| `POST` | `/chat` | Accepts `message`, `use_docs`, and optional `project`; returns an answer and sources. |
| `WS` | `/chat/stream` | Authenticated chat channel that returns the answer, sources, and completion event. |
| `GET` | `/search?q=...&k=4&project=...` | Returns shortened retrieved chunks and source paths. |
| `POST` | `/ingest` | Runs ingestion; accepts `full_reset` as a query parameter. |
| `POST` | `/files/move` | Moves a file inside `ALLOWED_ROOT`; body is `{ "src": "...", "dst": "..." }`. |
| `POST` | `/files/organize` | Sorts immediate files by extension; body is `{ "folder": "..." }`. |

Example chat request:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/chat" `
   -H "Authorization: Bearer <token>" `
   -H "Content-Type: application/json" `
   -d '{"message":"Summarize the indexed project notes","use_docs":true}'
```

## Running the desktop client

Install dependencies:

```powershell
cd locali-desktop
npm install
```

Start Vite and Electron together:

```powershell
npm run dev
```

The renderer uses `http://localhost:5173`. Electron connects to the backend on `127.0.0.1:8000` and Ollama on `127.0.0.1:11434`.

| Command | Purpose |
| --- | --- |
| `npm run dev:vite` | Start only Vite. |
| `npm run dev:electron` | Start Electron after Vite is ready. |
| `npm run dev` | Start Vite and Electron together. |
| `npm run lint` | Run Oxlint and CSS Stylelint. |
| `npm run build` | Build the renderer with Vite. |
| `npm run build:electron` | Build the renderer and invoke Electron Builder. |
| `npm run preview` | Preview the Vite production build. |

On Windows PowerShell, use `npm.cmd` if execution policy blocks `npm.ps1`, for example `npm.cmd run lint`.

## File-operation safety

The assistant can call these tools when the user explicitly requests a file operation:

- `list_files`
- `move_file`
- `create_folder`
- `organize_by_extension`
- `find_empty_files`

Tool paths are resolved against `ALLOWED_ROOT`. Traversal paths, absolute paths outside the root, and sibling-prefix escapes are rejected. Successful and blocked operations are recorded in `logs/actions.log` and mirrored into SQLite where applicable.

Verify the hash chain with:

```powershell
python -c "from app.tool.tools import verify_log_integrity; print(verify_log_integrity())"
```

The hash chain detects edits, deletions, and reordering after the fact; it does not prevent a process with filesystem access from deleting the log.

## Persistence and generated data

[app/database.py](app/database.py) creates `assistant.db` with tables for conversations, messages, and audit records. The following are local runtime data and should not be committed:

- `.venv/`
- `.auth_token`
- `assistant.db`
- `vector_store/`
- `logs/`
- `locali-desktop/node_modules/`, `dist/`, and `release/`
- Scanned personal files and workspace contents under `app/AI-Workspace/`

## Testing

From the repository root:

```powershell
.venv\Scripts\Activate.ps1
python -m unittest discover -s tests -v
```

The tests now import the packaged modules, for example `app.config`, `app.AI.ingest`, `app.AI.retriever`, `app.database`, and `app.tool.tools`. Coverage includes file-tool safety, persistence, retrieval/reranking, and an Ollama-dependent ingestion-to-answer integration test.

The integration test requires Ollama and the required models. Retrieval evaluation helpers use [fixtures/retrieval_eval.yaml](fixtures/retrieval_eval.yaml) and [fixtures/retrieval_pool.txt](fixtures/retrieval_pool.txt).

Desktop validation:

```powershell
cd locali-desktop
npm.cmd run lint
npm.cmd run build
```

## Known limitations

- The WebSocket endpoint currently sends the completed answer as one token event; it is not true token streaming.
- Ingestion runs synchronously in the API request and has no job ID, progress API, cancellation, or single-flight lock.
- API-triggered ingestion currently does not automatically prune stale entries.
- Some desktop IPC methods are ahead of the backend contracts, including file listing and ingestion fields.
- Conversation persistence is implemented in SQLite, but the normal successful `ask()` return path does not yet save every turn consistently.
- Electron Builder currently packages only `dist/` and Electron files. It does not bundle Python, the backend, Tesseract, or Ollama models.
- The default `SCAN_DRIVES` includes a whole drive. Narrow it before production use and review exclusions carefully.
- The cross-encoder may download from Hugging Face on first use unless already cached.

See [PROJECT_REVIEW.md](PROJECT_REVIEW.md) for the detailed review, validation results, and recommended delivery order.

## Roadmap

The full backlog is in [DOCS/Local_AI_Workspace_Assistant_Backlog.md](DOCS/Local_AI_Workspace_Assistant_Backlog.md):

1. MVP ingestion, retrieval, chat, and safe file tools.
2. Backend service, persistence, authentication, and retrieval improvements.
3. Desktop GUI, settings, search, dashboard, and packaging.
4. Multi-agent workflows, long-term memory, and automation.
5. Permissioned plugin discovery and distribution.

The immediate priority is to finish the package-layout migration, align desktop/backend contracts, fix persistence and indexing identity issues, and add end-to-end desktop workflow tests.
