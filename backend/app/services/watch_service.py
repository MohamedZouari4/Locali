"""File watcher: keeps each project's catalog and the search index up to date while the Core runs.

One background thread watches every project folder and every indexed folder (watchfiles, which uses
ReadDirectoryChangesW on Windows and inotify on Linux). Changes are collected for WATCH_DEBOUNCE_MS and
handled together:
- each project whose folders contain a changed path gets its catalog updated (catalog_service.apply_changes);
- index entries of deleted files are removed at once, so those files drop out of answers without
  waiting for Ollama;
- new and changed files in the indexed folders are queued as a `reindex` job, which replaces their chunks.
Changes in system, private or ignored folders, and to sensitive files, are dropped first. The folder list
is read again every WATCH_FOLDERS_CHECK_SECONDS, so added and removed folders are picked up.
"""

import logging
import os
import threading

from watchfiles import watch

from app.ai.ingestion import store
from app.ai.ingestion.walker import exclusion_reason, is_under, scan_roots, walk_data_dir
from app.ai.retrieval.sparse_retriever import all_sources, invalidate_caches
from app.core import config
from app.db import database
from app.services import catalog_service, rag_service

log = logging.getLogger(__name__)


def _outermost(paths):
    # Watching a folder also watches everything inside it, so nested folders would report each change twice.
    kept = []
    for path in sorted(set(paths), key=len):
        if not any(is_under(path, outer) for outer in kept):
            kept.append(path)
    return sorted(kept)


def watched_folders():
    """The existing folders to watch: every project folder and every folder chosen for indexing."""
    paths = [path for folders in database.list_all_project_folders().values() for path in folders]
    paths += [folder["path"] for folder in database.list_indexed_folders()]
    return _outermost(path for path in paths if os.path.isdir(path))


def keep_change(_change, path):
    """watchfiles filter: drops changes the catalog and the index must never see."""
    return os.path.basename(path) not in config.SENSITIVE_FILES and exclusion_reason(path) is None


def _update_index(paths):
    roots = scan_roots()
    paths = [path for path in paths if any(is_under(path, root) for root in roots)]
    if not paths:
        return
    gone = [path for path in paths if not os.path.exists(path)]
    if gone:
        # A deleted folder arrives as one path, so match every indexed source under it.
        stale = [source for source in all_sources() if any(is_under(source, path) for path in gone)]
        for source in stale:
            store.delete_source(source)
        if stale:
            invalidate_caches()
    present = []
    for path in paths:
        if os.path.isdir(path):
            present.extend(walk_data_dir([path]))
        elif os.path.isfile(path):
            present.append(path)
    if present:
        rag_service.start_reindex(present)


def handle_changes(paths):
    """Applies one batch of changed paths (absolute) to the catalogs and the index."""
    paths = sorted(set(paths))
    for project_id, folders in database.list_all_project_folders().items():
        if any(is_under(path, folder) for path in paths for folder in folders):
            catalog_service.apply_changes(project_id, folders, paths)
    _update_index(paths)


class FolderWatcher:
    """Runs the watch loop on one background thread until stop() is called."""

    def __init__(self):
        self._stopping = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="file-watcher", daemon=True)
        self._thread.start()

    def stop(self, timeout=10):
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self):
        while not self._stopping.is_set():
            folders = watched_folders()
            if not folders:
                self._stopping.wait(config.WATCH_FOLDERS_CHECK_SECONDS)
                continue
            try:
                for changes in watch(
                    *folders,
                    watch_filter=keep_change,
                    debounce=config.WATCH_DEBOUNCE_MS,
                    stop_event=self._stopping,
                    rust_timeout=int(config.WATCH_FOLDERS_CHECK_SECONDS * 1000),
                    yield_on_timeout=True,
                    raise_interrupt=False,
                ):
                    if changes:
                        try:
                            handle_changes(path for _, path in changes)
                        except Exception:
                            log.exception("File watcher could not apply %d change(s)", len(changes))
                    if watched_folders() != folders:
                        break  # watch the new folder list
            except Exception:
                log.exception("File watcher error; retrying after the folder check interval")
                self._stopping.wait(config.WATCH_FOLDERS_CHECK_SECONDS)


_watcher = None


def start():
    """Starts the watcher. Called when the backend starts."""
    global _watcher
    _watcher = FolderWatcher()
    _watcher.start()


def stop():
    global _watcher
    if _watcher is not None:
        _watcher.stop()
        _watcher = None
