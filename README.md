# Local AI Workspace Assistant

A local-first RAG (retrieval-augmented generation) pipeline that indexes files on your machine — documents, code, images, PSDs — into a searchable vector store, then answers questions about them using a locally-hosted LLM via [Ollama](https://ollama.com). No cloud APIs, no data leaves your machine.

See [`DOCS/`](DOCS/) for the full software design document and development backlog.

## Features

- **Multi-format ingestion** — extracts text from `.pdf`, `.docx`, `.txt`, `.md`, `.csv`, source code files, `.psd` (layer names + text layers), and images (`.jpg`/`.png`/etc. via Tesseract OCR)
- **Incremental indexing** — tracks each file's modification time so re-running the ingest only re-embeds files that actually changed
- **Configurable scan scope** — index a specific folder or entire drives, with built-in exclusion of system directories, dev-tool caches, and sensitive paths (`.ssh`, credential stores, etc.)
- **Local embeddings & LLM** — uses Ollama (`nomic-embed-text` for embeddings, `qwen3:4b` for chat) and [ChromaDB](https://www.trychroma.com/) as the vector store, entirely offline

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

## Usage

**Index files:**
```
python ingest.py
```
Extracts text, chunks it, embeds it via Ollama, and stores it in `vector_store/`. Safe to re-run — unchanged files are skipped.

**Query the index:**
```python
from retriever import retrieve

results = retrieve("your question here", k=4)
for chunk, source in results:
    print(source, "->", chunk[:100])
```

## Project structure

```
config.py       # paths, models, scan scope, exclusion lists
ingest.py       # file walking, text extraction, chunking, embedding, indexing
retriever.py    # query the vector store for relevant chunks
DOCS/           # software design document & development backlog
```

## Status

Work in progress — Phase 1 (CLI-based ingestion + retrieval) is functional. See [`DOCS/Local_AI_Workspace_Assistant_Backlog.md`](DOCS/Local_AI_Workspace_Assistant_Backlog.md) for the full roadmap (chat interface, publishing integrations, etc.).
