"""Baseline run (P0-E7-T2): asks each question in a fixture file through the real chat path and records
retrieval time, time to first token, total time and memory. Correctness is judged by hand afterwards.

Usage (from the backend folder, with Ollama running and one real folder indexed):
    python -m scripts.baseline --questions ../docs/private/baseline/questions.yaml --json ../docs/private/baseline/2026-10-07.json

The questions quote personal documents, so they stay in docs/private (git-ignored); docs/BASELINE.md holds the numbers.

Retrieval is timed with a separate call before the answer, so it runs twice per question; the
first-token time therefore includes a second (warm) retrieval.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import statistics
import subprocess
import sys
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import requests
import yaml

from app.ai.chat.orchestrator import ask_stream
from app.ai.ingestion.store import get_collection, indexed_sources
from app.ai.retrieval import retrieve
from app.chat_events import SourcesEvent, TokenEvent
from app.core.config import CHAT_MODEL, EMBEDDING_MODEL, OLLAMA_URL, RERANK_ENABLED, RERANK_MODEL

WARMUP_QUESTION = "Say hello in one word."


class _MemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def backend_memory_mb():
    """Current and peak working set of this Python process, in MB (Windows only)."""
    if sys.platform != "win32":
        return None, None
    kernel32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MemoryCounters), wintypes.DWORD]
    counters = _MemoryCounters(cb=ctypes.sizeof(_MemoryCounters))
    psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
    return round(counters.WorkingSetSize / 2**20), round(counters.PeakWorkingSetSize / 2**20)


def ollama_memory():
    """Memory of each loaded Ollama model: total MB and the share held on the GPU."""
    models = requests.get(f"{OLLAMA_URL}/api/ps", timeout=5).json().get("models", [])
    return [
        {
            "model": m["name"],
            "size_mb": round(m["size"] / 2**20),
            "gpu_percent": round(100 * m.get("size_vram", 0) / m["size"]) if m["size"] else 0,
        }
        for m in models
    ]


def git_commit():
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def ask_timed(question, project=None):
    started = time.perf_counter()
    retrieve(question, 4, project=project)
    retrieval_s = time.perf_counter() - started

    started = time.perf_counter()
    first_token_s, parts, sources = None, [], []
    for event in ask_stream(question, use_docs=True, project=project):
        if isinstance(event, TokenEvent):
            if first_token_s is None:
                first_token_s = time.perf_counter() - started
            parts.append(event.text)
        elif isinstance(event, SourcesEvent):
            sources = event.sources
    total_s = time.perf_counter() - started

    return {
        "retrieval_s": round(retrieval_s, 2),
        "first_token_s": round(first_token_s, 2) if first_token_s is not None else None,
        "total_s": round(total_s, 2),
        "answer": "".join(parts),
        "sources": sorted(set(sources)),
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", required=True)
    parser.add_argument("--json", help="also write the full results here")
    args = parser.parse_args()

    fixture = yaml.safe_load(Path(args.questions).read_text(encoding="utf-8"))
    project = fixture.get("project")

    cold = ask_timed(WARMUP_QUESTION, project)
    rows = []
    for item in fixture["questions"]:
        result = ask_timed(item["question"], project)
        result["backend_mb"], _ = backend_memory_mb()
        rows.append({"id": item["id"], "question": item["question"], "expect": item.get("expect", ""), **result, "correct": None})
        print(
            f"\n--- {item['id']}: {item['question']}\nexpect:  {item.get('expect', '')}\n"
            f"answer:  {result['answer']}\nsources: {', '.join(result['sources']) or '(none)'}"
        )

    _, peak_mb = backend_memory_mb()
    models = ollama_memory()
    info = {
        "date": datetime.now().isoformat(timespec="minutes"),
        "commit": git_commit(),
        "folder": fixture.get("folder"),
        "chat_model": CHAT_MODEL,
        "embedding_model": EMBEDDING_MODEL,
        "reranker": RERANK_MODEL if RERANK_ENABLED else "off",
        "indexed_files": len(indexed_sources()),
        "indexed_chunks": get_collection().count(),
        "cold_start": {k: cold[k] for k in ("retrieval_s", "first_token_s", "total_s")},
        "backend_peak_mb": peak_mb,
        "ollama_models": models,
    }

    print("\n\n| # | Question | Retrieval s | First token s | Total s | Backend MB | Correct |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['id']} | {r['question']} | {r['retrieval_s']} | {r['first_token_s']} | {r['total_s']} | {r['backend_mb']} |  |")

    first_tokens = [r["first_token_s"] for r in rows if r["first_token_s"] is not None]
    totals = [r["total_s"] for r in rows]
    print(
        f"\nmedian first token {statistics.median(first_tokens):.2f} s   "
        f"median total {statistics.median(totals):.2f} s   max total {max(totals):.2f} s"
    )
    print(f"cold start: {info['cold_start']}")
    print(f"backend peak {peak_mb} MB   ollama: {models}")
    print(f"index: {info['indexed_files']} files, {info['indexed_chunks']} chunks   commit {info['commit']}")

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({**info, "questions": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nwritten to {args.json}")


if __name__ == "__main__":
    main()
