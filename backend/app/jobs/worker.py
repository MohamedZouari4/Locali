"""Background job worker. Jobs are rows in the SQLite jobs table (app.db.database). One worker
thread inside the backend runs them oldest first, never two for the same project at once.

A job kind is a function registered with @handler("kind"). It receives the job's params and a
JobContext for reporting progress and checking for cancellation, and returns a JSON-serialisable
result. Use submit() to queue a job.
"""

import logging
import threading
import time

from app.core.config import JOB_POLL_SECONDS, JOB_PROGRESS_INTERVAL_SECONDS
from app.db import database

log = logging.getLogger(__name__)

HANDLERS = {}


def handler(kind):
    """Registers the decorated function as the handler for jobs of this kind."""

    def register(fn):
        HANDLERS[kind] = fn
        return fn

    return register


class JobCancelled(Exception):
    """Raised by JobContext.check_cancelled() when the job was asked to stop."""


class JobContext:
    """Passed to a handler so it can report progress and stop when cancelled."""

    def __init__(self, job_id, clock=time.monotonic):
        self.job_id = job_id
        self._clock = clock
        self._last_saved = None

    def progress(self, current, total=None, message=None):
        # Saved at most once per JOB_PROGRESS_INTERVAL_SECONDS, so a job reporting every file
        # doesn't write to the database every file.
        now = self._clock()
        if self._last_saved is None or now - self._last_saved >= JOB_PROGRESS_INTERVAL_SECONDS:
            database.update_job_progress(self.job_id, current, total, message)
            self._last_saved = now

    def check_cancelled(self):
        """Call between steps of a long job; raises JobCancelled if someone cancelled it."""
        if database.is_cancel_requested(self.job_id):
            raise JobCancelled()


def run_job(job):
    """Runs one claimed job and records how it ended: done, failed or cancelled."""
    fn = HANDLERS.get(job["kind"])
    if fn is None:
        database.finish_job(job["id"], "failed", error=f"Unknown job kind '{job['kind']}'")
        return

    result, error = None, None
    try:
        result = fn(job["params"], JobContext(job["id"]))
        state = "done"
    except JobCancelled:
        state = "cancelled"
    except Exception as exc:
        log.exception("Job %s (%s) failed", job["id"], job["kind"])
        state, error = "failed", f"{type(exc).__name__}: {exc}"

    try:
        database.finish_job(job["id"], state, result=result, error=error)
    except (TypeError, ValueError) as exc:  # the result can't be stored as JSON
        database.finish_job(job["id"], "failed", error=f"Could not save the job result: {exc}")


class Worker:
    """Runs queued jobs on one background thread until stop() is called."""

    def __init__(self, poll_seconds=JOB_POLL_SECONDS):
        self._poll_seconds = poll_seconds
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="job-worker", daemon=True)
        self._thread.start()

    def wake(self):
        """Starts a newly queued job now instead of at the next poll."""
        self._wake.set()

    def stop(self, timeout=10):
        """Stops after the current job. A job still running when the process exits is marked
        failed at the next start by recover_interrupted_jobs()."""
        self._stopping.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self):
        while not self._stopping.is_set():
            try:
                job = database.claim_next_job()
                if job is not None:
                    run_job(job)
                    continue
            except Exception:
                log.exception("Job worker error; retrying after the poll interval")
            self._wake.wait(self._poll_seconds)
            self._wake.clear()


_worker = None


def start_worker():
    """Fails jobs a previous run left running, then starts the worker. Called when the backend starts."""
    global _worker
    interrupted = database.recover_interrupted_jobs()
    if interrupted:
        log.warning("Marked %d interrupted job(s) as failed", interrupted)
    _worker = Worker()
    _worker.start()


def stop_worker():
    global _worker
    if _worker is not None:
        _worker.stop()
        _worker = None


def submit(kind, params=None, project="default"):
    """Queues a job and returns its id. It runs as soon as its project has no other job running."""
    job_id = database.enqueue_job(kind, params, project)
    if _worker is not None:
        _worker.wake()
    return job_id
