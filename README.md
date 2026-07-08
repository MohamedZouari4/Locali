# Local AI Workspace Assistant

A local-first RAG (retrieval-augmented generation) pipeline that indexes files on your machine — documents, code, images, PSDs — into a searchable vector store, then answers questions about them using a locally-hosted LLM via [Ollama](https://ollama.com). No cloud APIs, no data leaves your machine.

The full software design document and development backlog are kept in a local `DOCS/` folder, which is gitignored (not part of this repo).

## Features

- **Multi-format ingestion** — extracts text from `.pdf`, `.docx`, `.txt`, `.md`, `.csv`, source code files, `.psd` (layer names + text layers), and images (`.jpg`/`.png`/etc. via Tesseract OCR)
- **Incremental indexing** — tracks each file's modification time so re-running the ingest only re-embeds files that actually changed
- **Configurable scan scope** — index a specific folder or entire drives, with built-in exclusion of system directories, dev-tool caches, and sensitive paths (`.ssh`, credential stores, etc.)
- **Stale-entry pruning** — removes index entries for files that were deleted or fell outside the scan scope/exclusion rules since they were last indexed (`ingest.py --prune-only`)
- **Project-aware retrieval** — auto-detects a project/file keyword in a query (e.g. "Contify") and restricts the vector search to matching sources first, so a specifically-named file doesn't lose to generic content on pure semantic similarity
- **Local embeddings & LLM** — uses Ollama (`nomic-embed-text` for embeddings, `qwen3:4b` for chat) and [ChromaDB](https://www.trychroma.com/) as the vector store, entirely offline
- **Sandboxed file operations via tool calling** — the model can list, move, create, organize, and search for empty files, but only inside a configured `ALLOWED_ROOT` workspace folder; every path is validated against traversal/escape before any operation runs, and multi-step requests (e.g. "move empty files to a new folder") are handled by looping the model through several tool calls until the request is complete
- **Tamper-evident action log** — every file operation is appended to a hash-chained log (`logs/actions.log`), recording who/what ran it (OS user, hostname, PID) and linking each entry to the previous one's hash so any edit, deletion, or reordering after the fact is detectable via `tools.verify_log_integrity()`
- **Interactive CLI** — `main.py` provides a chat loop; prefix a question with `doc:` to ground the answer in your indexed files; run with `--debug` to print retrieval results, prompts, and tool-call traces

## Stack

- **Vector store:** ChromaDB (persistent, local SQLite-backed)
- **Embeddings / chat model:** Ollama (`nomic-embed-text`, `qwen3:4b`)
- **Text extraction:** `pypdf`, `python-docx`, `psd-tools`, `pytesseract` + Pillow
- **OCR engine:** Tesseract (external install, not bundled)

## Setup

1. **Install Python 3.11+** and create a virtual environment:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. **Install [Ollama](https://ollama.com)** and pull the required models:
   ```
   ollama pull nomic-embed-text
   ollama pull qwen3:4b
   ```
3. **Install [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)** (Windows build) and note its install path.
4. **Configure `config.py`** for your machine:
   - `TESSRACT_PATH` — path to your Tesseract executable
   - `SCAN_DRIVES` / `DATA_DIR` — folder(s) or drives to index
   - `IGNORE_DIRS` / `SYSTEM_EXCLUDE` / `SENSITIVE_FILES` — adjust exclusions as needed for your system
   - `ALLOWED_ROOT` — the only folder the model's file-operation tools (move/create/organize/etc.) are allowed to touch

## Usage

**Index files:**
```
python ingest.py
```
Extracts text, chunks it, embeds it via Ollama, and stores it in `vector_store/`. Safe to re-run — unchanged files are skipped. Also prunes stale/excluded entries afterward; run `python ingest.py --prune-only` to just prune without a full re-scan.

**Chat interactively:**
```
python main.py
```
Ask anything; prefix with `doc:` to ground the answer in your indexed files (e.g. `doc: what does the Contify project do`), or ask it to perform a file operation inside `ALLOWED_ROOT` (e.g. `organize my workspace by file type`). Type `exit` to quit. Add `--debug` to print retrieval/prompt/tool-call internals.

**Query the index directly:**
```python
from retriever import retrieve

results = retrieve("your question here", k=4)
for chunk, source in results:
    print(source, "->", chunk[:100])
```

**Use the orchestrator programmatically:**
```python
from orchestrator import ask

answer, sources, used_tools = ask("what does the Contify project do", use_docs=True, project="Contify")
```

**Verify the action log hasn't been tampered with:**
```python
from tools import verify_log_integrity

ok, bad_line = verify_log_integrity()
```

## Project structure

```
config.py       # paths, models, scan scope, exclusion lists
ingest.py       # file walking, text extraction, chunking, embedding, indexing, pruning
retriever.py    # query the vector store for relevant chunks, with project-aware scoping
orchestrator.py # builds RAG context/prompts, defines the tool schema, and drives the tool-calling loop
tools.py        # sandboxed file-operation tools (list/move/create/organize/find-empty), tamper-evident logging
main.py         # interactive CLI chat loop
tests/          # unit tests (tools.py) and an Ollama-dependent integration test (ingest -> ask -> citation)
```

## Testing

```
python -m unittest discover -s tests -v
```
Unit tests run in an isolated temp directory and require no external services. The integration test additionally requires a running Ollama instance with `nomic-embed-text` and `qwen3:4b` pulled — it skips automatically if either isn't available.

## Status

Work in progress — Phase 1 (CLI-based ingestion + retrieval + interactive chat + sandboxed file operations) is functional. The full roadmap (publishing integrations, etc.) lives in the local, gitignored `DOCS/` folder.
