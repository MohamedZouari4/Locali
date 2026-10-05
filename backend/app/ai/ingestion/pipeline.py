"""Ingestion pipeline: walks the scan roots (folders chosen in the app plus SCAN_DRIVES), extracts
text from supported files, redacts PII and secrets, splits the text into section chunks, embeds them
with Ollama and stores them in ChromaDB.

Run from the backend folder: `python -m app.ai.ingestion.pipeline` to ingest then prune stale entries,
or pass `--prune-only` or `--search "query" [--source-type code]`.
"""

import hashlib
import os
import time
from pathlib import Path

from app.ai.ingestion import store
from app.ai.ingestion.chunking import chunk_by_section, make_document_id
from app.ai.ingestion.extractors import get_source_type, read_text, sniff_mime
from app.ai.ingestion.walker import is_excluded_path, is_under, scan_roots, walk_data_dir
from app.core import config

MAX_FILE_SIZE_MB = 25


def file_hash(filepath, chunk_size=1024 * 1024):
    """Return the SHA-256 digest of a file without loading it all into memory."""
    digest = hashlib.sha256()
    with open(filepath, "rb") as file:
        for chunk in iter(lambda: file.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prune_stale(progress_every=2000, report=None):
    """Remove index entries whose source file no longer exists or no longer
    satisfies the current scan/exclusion rules (e.g. its folder is no longer indexed,
    or a directory it lives under was added to IGNORE_DIRS/PRIVACY_EXCLUDE since
    it was indexed).

    `report(current, total, message)`, when given, is called before each source is checked.
    """
    roots = scan_roots()
    # Every path counts as excluded when there are no roots, so pruning would wipe the index.
    if not roots:
        print("No folders to index (none chosen in the app, SCAN_DRIVES empty); nothing to prune.")
        return 0
    sources = store.indexed_sources()
    removed = 0
    for checked, source in enumerate(sources, start=1):
        if report:
            report(checked - 1, len(sources), "Removing deleted files from the index")
        if checked % progress_every == 0:
            print(f"...checked {checked} sources, removed {removed} so far")
        if not os.path.exists(source) or is_excluded_path(source, roots):
            store.delete_source(source)
            removed += 1
    print(f"Pruned {removed} stale/excluded sources out of {len(sources)} checked")
    return removed


def forget_folder(folder, report=None):
    """Remove the index entries for files under `folder`, except those still under another scan root.

    Used when a folder is taken off the indexed list, so its files stop appearing in answers. Works
    even when no roots are left, unlike prune_stale.
    """
    remaining = scan_roots()
    sources = store.indexed_sources()
    removed = 0
    for checked, source in enumerate(sources, start=1):
        if report:
            report(checked - 1, len(sources), "Removing the folder's files from the index")
        if is_under(source, folder) and not any(is_under(source, root) for root in remaining):
            store.delete_source(source)
            removed += 1
    print(f"Removed {removed} sources under {folder}")
    return removed


def ingest_all(max_size_mb=MAX_FILE_SIZE_MB, progress_every=500, report=None):
    """Index every new or changed file under the scan roots and return the counts.

    `report(current, total, message)`, when given, is called while files are being found and
    before each file is processed. It may raise to stop the run, as a cancelled job does; the
    files indexed so far stay indexed.
    """
    roots = scan_roots()
    if not roots:
        print("No folders to index (none chosen in the app, SCAN_DRIVES empty); nothing to ingest.")
        return {"indexed": 0, "chunks": 0, "skipped": 0, "unchanged": 0, "scanned": 0}
    chunk_total, indexed, skipped, unchanged = 0, 0, 0, 0
    start_time = time.time()

    # Find the files first, so progress can show a total.
    paths = []
    for path in walk_data_dir(roots):
        paths.append(path)
        if report:
            report(len(paths), None, f"Finding files ({len(paths):,} so far)")
    total = len(paths)
    print(f"Found {total} files in {time.time() - start_time:.0f}s")

    for scanned, path in enumerate(paths, start=1):
        # Outside the per-file try below, so an exception from `report` stops the run instead of skipping a file.
        if report:
            report(scanned - 1, total, f"Indexing {os.path.basename(path)}")
        if scanned % progress_every == 0:
            elapsed = time.time() - start_time
            rate = scanned / elapsed
            print(
                f"...scanned {scanned} of {total} files in {elapsed:.0f}s ({rate:.1f} files/s) "
                f"- indexed {indexed}, unchanged {unchanged}, skipped {skipped}"
            )

        if path.lower().rsplit(".", 1)[-1] in config.SKIP_EXTENSIONS:
            skipped += 1
            continue

        source = os.path.abspath(path)
        try:
            ext = Path(source).suffix.lower().lstrip(".") or "unknown"
            file_size = os.path.getsize(path)
            if file_size > max_size_mb * 1024 * 1024:
                print(f"Skipped {path}: file too large (>{max_size_mb}MB)")
                skipped += 1
                continue

            sniffed_kind, is_safe = sniff_mime(path, ext)
            if not is_safe:
                print(f"Skipped {path}: MIME pre-check failed (sniffed as '{sniffed_kind}', declared .{ext})")
                skipped += 1
                continue

            content_hash = file_hash(path)
            if store.stored_hash(source) == content_hash:
                unchanged += 1
                continue

            print(f"Processing: {path}")
            mtime = os.path.getmtime(path)
            text = read_text(path)
            if text:
                text = text.encode("utf-8", "ignore").decode("utf-8")
        except Exception as error:
            print(f"Skipped {path}: {error}")
            skipped += 1
            continue

        if not text or not text.strip():
            print("  -> skipped (empty)")
            skipped += 1
            continue

        source_type = get_source_type(ext)
        chunks = chunk_by_section(text, make_document_id(content_hash), source, ext, source_type)

        store.replace_source_chunks(source, chunks, mtime, content_hash)
        chunk_total += len(chunks)
        indexed += 1
        print(f"  -> indexed ({len(chunks)} chunks)")

    elapsed = time.time() - start_time
    print(
        f"Indexed {indexed} files ({chunk_total} chunks), skipped {skipped} unsupported/empty/oversized files, "
        f"{unchanged} unchanged, {total} scanned total in {elapsed:.0f}s"
    )
    return {"indexed": indexed, "chunks": chunk_total, "skipped": skipped, "unchanged": unchanged, "scanned": total}


if __name__ == "__main__":
    import sys

    if "--prune-only" in sys.argv:
        prune_stale()
    elif "--search" in sys.argv:
        query_text = sys.argv[sys.argv.index("--search") + 1]
        source_type_filter = None
        if "--source-type" in sys.argv:
            source_type_filter = sys.argv[sys.argv.index("--source-type") + 1]
        results = store.search(query_text, source_type=source_type_filter)
        for document, metadata in zip(results["documents"][0], results["metadatas"][0]):
            print(f"[{metadata.get('source_type')}] {metadata.get('source')} :: {metadata.get('heading_path')}")
            print(document[:200])
            print("---")
    else:
        ingest_all()
        prune_stale()
