"""Idle-time pre-extraction: while nobody is using the computer, the text of small catalogued files is
read into the text cache in the background, so a first question about them doesn't wait for extraction.

It must never slow down active use, so it only works while all of these hold, checked again before
every file:
- PREEXTRACT_ENABLED is on;
- there has been no keyboard or mouse input for PREEXTRACT_IDLE_SECONDS (system_activity);
- the computer runs on mains power, with battery saver off;
- Locali has nothing else to do: no other job queued or running, and no chat reply being written.
Where idleness or power can't be read (outside Windows), nothing is pre-extracted.

The work runs as `preextract` jobs on the shared worker, which runs one job at a time. A job reads files
for at most PREEXTRACT_BATCH_SECONDS and ends as soon as a condition stops holding, so a job the user
starts waits at most for the file being read. A scheduler thread queues the next job every
PREEXTRACT_CHECK_SECONDS while files are waiting and the conditions hold.

Only files up to PREEXTRACT_MAX_FILE_MB with a quick text reader are taken, most recently modified first;
images (OCR) and Photoshop files wait for a real read. A file that can't be read is skipped until the
backend restarts, so it isn't tried again in every job.

Importing this module registers the `preextract` job kind; app/api/main.py imports it.
"""

import logging
import threading
import time

from app.ai.ingestion.extractors import EXTRACTOR_VERSION
from app.core import config, system_activity
from app.db import database
from app.jobs import worker
from app.services import text_cache_service

log = logging.getLogger(__name__)

PREEXTRACT_KIND = "preextract"
EXTENSIONS = config.CODE_EXTENSIONS | {"pdf", "docx", "csv"}
BATCH_FILES = 200  # files listed per job; the time budget usually ends a job first

# Catalog ids of files that couldn't be read, skipped until the backend restarts.
_unreadable = set()


def pause_reason(own_job=False):
    """Why pre-extraction must wait now ("disabled", "unsupported", "user_active", "battery" or "busy"), or
    None when it may run. A running preextract job passes own_job=True, so it doesn't count itself as busy."""
    if not config.PREEXTRACT_ENABLED:
        return "disabled"
    idle = system_activity.idle_seconds()
    battery = system_activity.on_battery()
    if idle is None or battery is None:
        return "unsupported"
    if idle < config.PREEXTRACT_IDLE_SECONDS:
        return "user_active"
    if battery:
        return "battery"
    if database.has_active_work(except_kind=PREEXTRACT_KIND if own_job else None):
        return "busy"
    return None


def files_to_read(limit=BATCH_FILES):
    """Catalogued files whose current text isn't cached yet and that are worth reading ahead."""
    max_size = config.PREEXTRACT_MAX_FILE_MB * 1024 * 1024
    return database.list_uncached_files(EXTRACTOR_VERSION, max_size, EXTENSIONS, _unreadable, limit)


def read_ahead(check_cancelled=lambda: None, clock=time.monotonic):
    """Reads waiting files into the text cache until PREEXTRACT_BATCH_SECONDS are spent, the listed files
    are read, or pre-extraction must pause. Returns {"read", "unreadable", "stopped"}, where "stopped" is
    "done", "time" or the pause reason."""
    deadline = clock() + config.PREEXTRACT_BATCH_SECONDS
    read = unreadable = 0
    for file in files_to_read():
        stopped = pause_reason(own_job=True) or ("time" if clock() >= deadline else None)
        if stopped:
            return {"read": read, "unreadable": unreadable, "stopped": stopped}
        check_cancelled()
        try:
            text_cache_service.read_text(file["project_id"], file["id"])
            read += 1
        except text_cache_service.TextUnavailable:
            _unreadable.add(file["id"])
            unreadable += 1
    return {"read": read, "unreadable": unreadable, "stopped": "done"}


@worker.handler(PREEXTRACT_KIND, single_flight=True)
def run_preextract_job(_params, ctx):
    return read_ahead(ctx.check_cancelled)


def queue_if_idle():
    """Queues a preextract job if pre-extraction may run and a file is waiting. Returns the job id, or None."""
    if pause_reason() is not None or not files_to_read(limit=1):
        return None
    try:
        return worker.submit(PREEXTRACT_KIND, project=PREEXTRACT_KIND)
    except worker.JobAlreadyActive:
        return None


class Scheduler:
    """Calls queue_if_idle every PREEXTRACT_CHECK_SECONDS on one background thread until stop() is called."""

    def __init__(self):
        self._stopping = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="preextract-scheduler", daemon=True)
        self._thread.start()

    def stop(self, timeout=10):
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self):
        while not self._stopping.wait(config.PREEXTRACT_CHECK_SECONDS):
            try:
                queue_if_idle()
            except Exception:
                log.exception("Pre-extraction scheduler error; trying again at the next check")


_scheduler = None


def start():
    """Starts the scheduler, unless pre-extraction is turned off. Called when the backend starts."""
    global _scheduler
    if config.PREEXTRACT_ENABLED:
        _scheduler = Scheduler()
        _scheduler.start()


def stop():
    global _scheduler
    if _scheduler is not None:
        _scheduler.stop()
        _scheduler = None
