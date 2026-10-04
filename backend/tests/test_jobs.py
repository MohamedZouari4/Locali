"""Tests for the job store and worker: states, progress, cancellation, restart recovery, and that
two jobs for the same project never run at once. Uses a temporary database and test-only job kinds.
"""

import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from app.db import database
from app.jobs import worker


def _wait_for(condition, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


class JobTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="jobs_test_")
        self._patches = [
            patch.object(database, "DB_PATH", os.path.join(self.tmpdir, "assistant_test.db")),
            patch.object(database, "_initialized", False),
            patch.dict(worker.HANDLERS, clear=True),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_next(self):
        job = database.claim_next_job()
        worker.run_job(job)
        return database.get_job(job["id"])


class JobStateTests(JobTestCase):
    def test_a_job_goes_from_queued_to_running_to_done(self):
        worker.HANDLERS["echo"] = lambda params, ctx: {"echo": params["word"]}
        job_id = database.enqueue_job("echo", {"word": "hi"})
        self.assertEqual(database.get_job(job_id)["state"], "queued")

        running = database.claim_next_job()
        self.assertEqual((running["id"], running["state"]), (job_id, "running"))

        worker.run_job(running)
        done = database.get_job(job_id)
        self.assertEqual((done["state"], done["result"]), ("done", {"echo": "hi"}))
        self.assertIsNotNone(done["finished_at"])

    def test_a_handler_error_fails_the_job_with_the_message(self):
        def broken(params, ctx):
            raise RuntimeError("disk is full")

        worker.HANDLERS["broken"] = broken
        database.enqueue_job("broken")

        with self.assertLogs("app.jobs.worker", level="ERROR"):
            job = self._run_next()
        self.assertEqual((job["state"], job["error"]), ("failed", "RuntimeError: disk is full"))

    def test_an_unknown_kind_fails(self):
        database.enqueue_job("no-such-kind")

        job = self._run_next()
        self.assertEqual((job["state"], job["error"]), ("failed", "Unknown job kind 'no-such-kind'"))

    def test_a_result_that_is_not_json_fails_the_job(self):
        worker.HANDLERS["odd"] = lambda params, ctx: {"when": object()}
        database.enqueue_job("odd")

        job = self._run_next()
        self.assertEqual(job["state"], "failed")
        self.assertIn("Could not save the job result", job["error"])

    def test_progress_is_saved(self):
        def halfway(params, ctx):
            ctx.progress(5, 10, "Indexing notes.md")

        worker.HANDLERS["halfway"] = halfway
        database.enqueue_job("halfway")

        job = self._run_next()
        self.assertEqual((job["progress_current"], job["progress_total"], job["progress_message"]), (5, 10, "Indexing notes.md"))

    def test_progress_is_saved_at_most_once_per_interval(self):
        job_id = database.enqueue_job("anything")
        database.claim_next_job()
        now = [100.0]
        ctx = worker.JobContext(job_id, clock=lambda: now[0])

        ctx.progress(1, 10)
        now[0] += 0.1
        ctx.progress(2, 10)  # too soon: not saved
        self.assertEqual(database.get_job(job_id)["progress_current"], 1)

        now[0] += worker.JOB_PROGRESS_INTERVAL_SECONDS
        ctx.progress(3, 10)
        self.assertEqual(database.get_job(job_id)["progress_current"], 3)


class CancelTests(JobTestCase):
    def test_cancelling_a_queued_job_cancels_it_at_once(self):
        job_id = database.enqueue_job("anything")

        self.assertEqual(database.cancel_job(job_id), "cancelled")
        self.assertIsNone(database.claim_next_job())

    def test_a_running_job_stops_at_its_next_check(self):
        def cancelled_while_running(params, ctx):
            database.cancel_job(ctx.job_id)  # as if the user clicked Cancel now
            ctx.check_cancelled()
            raise AssertionError("should have stopped")

        worker.HANDLERS["long"] = cancelled_while_running
        database.enqueue_job("long")

        self.assertEqual(self._run_next()["state"], "cancelled")

    def test_cancelling_an_unknown_job_returns_none(self):
        self.assertIsNone(database.cancel_job("missing"))


class RestartTests(JobTestCase):
    def test_after_a_restart_running_jobs_fail_and_queued_jobs_still_run(self):
        worker.HANDLERS["echo"] = lambda params, ctx: "ran"
        interrupted = database.enqueue_job("echo")
        waiting = database.enqueue_job("echo")
        database.claim_next_job()  # the first was running when the app stopped

        database._initialized = False  # the next connection runs startup again, like a restarted app
        self.assertEqual(database.recover_interrupted_jobs(), 1)

        failed = database.get_job(interrupted)
        self.assertEqual((failed["state"], failed["error"]), ("failed", "Interrupted by a restart"))
        self.assertEqual(database.get_job(waiting)["state"], "queued")
        self.assertEqual(self._run_next()["result"], "ran")

    def test_start_worker_recovers_then_runs_the_queue(self):
        worker.HANDLERS["echo"] = lambda params, ctx: "ran"
        interrupted = database.enqueue_job("echo")
        database.claim_next_job()
        waiting = database.enqueue_job("echo")

        with self.assertLogs("app.jobs.worker", level="WARNING"):
            worker.start_worker()
        try:
            self.assertTrue(_wait_for(lambda: database.get_job(waiting)["state"] == "done"))
        finally:
            worker.stop_worker()
        self.assertEqual(database.get_job(interrupted)["state"], "failed")


class OneJobPerProjectTests(JobTestCase):
    def test_claiming_skips_projects_that_already_have_a_running_job(self):
        first = database.enqueue_job("anything", project="p1")
        database.enqueue_job("anything", project="p1")
        other = database.enqueue_job("anything", project="p2")

        self.assertEqual(database.claim_next_job()["id"], first)
        self.assertEqual(database.claim_next_job()["id"], other)
        self.assertIsNone(database.claim_next_job())  # p1's second job waits

    def test_the_database_refuses_a_second_running_job_in_a_project(self):
        database.enqueue_job("anything", project="p1")
        second = database.enqueue_job("anything", project="p1")
        database.claim_next_job()

        with self.assertRaises(sqlite3.IntegrityError):
            with database._transaction() as conn:
                conn.execute("UPDATE jobs SET state = 'running' WHERE id = ?", (second,))

    def test_several_workers_never_run_two_jobs_of_one_project_at_once(self):
        lock = threading.Lock()
        running = {"p1": 0, "p2": 0}
        most_at_once = {"p1": 0, "p2": 0}

        def busy(params, ctx):
            project = params["project"]
            with lock:
                running[project] += 1
                most_at_once[project] = max(most_at_once[project], running[project])
            time.sleep(0.05)
            with lock:
                running[project] -= 1

        worker.HANDLERS["busy"] = busy
        job_ids = [database.enqueue_job("busy", {"project": p}, project=p) for p in ["p1"] * 4 + ["p2"] * 4]

        workers = [worker.Worker(poll_seconds=0.01) for _ in range(3)]
        for w in workers:
            w.start()
        try:
            self.assertTrue(_wait_for(lambda: all(database.get_job(j)["state"] == "done" for j in job_ids)))
        finally:
            for w in workers:
                w.stop()

        self.assertEqual(most_at_once, {"p1": 1, "p2": 1})


if __name__ == "__main__":
    unittest.main()
