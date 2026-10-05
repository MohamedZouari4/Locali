"""Tests for ingestion as a background job: the pipeline reports progress per file and stops when
cancelled, POST /ingest returns a job at once, and a second ingestion is refused while one is active.
Ollama and ChromaDB are replaced by mocks, so these run without them (and in CI).
"""

import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.ai.ingestion import pipeline
from app.api.main import app
from app.core.security import API_TOKEN
from app.db import database
from app.jobs import worker
from app.services import rag_service


class PipelineProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="ingest_job_test_")
        self.files = []
        for name in ["a.txt", "b.txt", "c.txt"]:
            path = os.path.join(self.tmpdir, name)
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"# {name}\n\nSome notes in {name}.\n")
            self.files.append(path)
        self.store = MagicMock()
        self.store.stored_hash.return_value = None  # every file is new
        self._patches = [
            patch.object(pipeline, "store", self.store),
            patch.object(pipeline, "walk_data_dir", return_value=iter(self.files)),
            patch.object(pipeline, "scan_roots", return_value=[self.tmpdir]),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_progress_is_reported_per_file_with_a_total(self):
        calls = []

        result = pipeline.ingest_all(report=lambda current, total, message: calls.append((current, total, message)))

        self.assertEqual(result["indexed"], 3)
        finding = [call for call in calls if call[1] is None]
        indexing = [call for call in calls if call[1] is not None]
        self.assertEqual([current for current, _, _ in finding], [1, 2, 3])
        self.assertEqual(indexing, [(0, 3, "Indexing a.txt"), (1, 3, "Indexing b.txt"), (2, 3, "Indexing c.txt")])

    def test_an_exception_from_report_stops_the_run_and_keeps_what_was_indexed(self):
        class Stop(Exception):
            pass

        def report(current, total, message):
            if total is not None and current == 2:
                raise Stop()

        with self.assertRaises(Stop):  # not swallowed by the per-file error handling
            pipeline.ingest_all(report=report)
        self.assertEqual(self.store.replace_source_chunks.call_count, 2)

    def test_without_report_it_behaves_as_before(self):
        self.assertEqual(pipeline.ingest_all()["scanned"], 3)


class IngestJobTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="ingest_job_test_")
        self._patches = [
            patch.object(database, "DB_PATH", os.path.join(self.tmpdir, "assistant_test.db")),
            patch.object(database, "_initialized", False),
            patch.dict(worker.HANDLERS, {rag_service.INGEST_KIND: rag_service.run_ingest_job}, clear=True),
            patch.object(worker, "SINGLE_FLIGHT", set(worker.SINGLE_FLIGHT)),  # as registered by rag_service
            patch.object(worker, "JOB_PROGRESS_INTERVAL_SECONDS", 0),
            patch.object(worker, "JOB_CANCEL_CHECK_SECONDS", 0),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class IngestRouteTests(IngestJobTestCase):
    # Without `with TestClient(app)` the worker doesn't start, so the job stays queued.
    def setUp(self):
        super().setUp()
        self.client = TestClient(app, headers={"Authorization": f"Bearer {API_TOKEN}"})

    def test_ingest_returns_a_queued_job_at_once(self):
        started = time.monotonic()
        response = self.client.post("/ingest?full_reset=true")

        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(response.status_code, 202)
        job = response.json()
        self.assertEqual((job["kind"], job["state"], job["params"]), ("ingest", "queued", {"full_reset": True}))

    def test_a_second_ingest_is_refused_with_a_clear_message(self):
        first = self.client.post("/ingest").json()

        second = self.client.post("/ingest")
        self.assertEqual(second.status_code, 409)
        self.assertIn("Indexing is already running", second.json()["detail"])
        # The generic route is held to the same rule, and names the job that is in the way.
        generic = self.client.post("/jobs", json={"kind": "ingest"})
        self.assertEqual(generic.status_code, 409)
        self.assertIn(f"already queued or running (job {first['id']}, queued)", generic.json()["detail"])

    def test_ingest_can_start_again_once_the_last_one_ended(self):
        first = self.client.post("/ingest").json()
        self.client.post(f"/jobs/{first['id']}/cancel")

        self.assertEqual(self.client.post("/ingest").status_code, 202)

    def test_status_returns_the_latest_ingestion_or_null(self):
        self.assertIsNone(self.client.get("/ingest/status").json())

        job_id = self.client.post("/ingest").json()["id"]
        self.assertEqual(self.client.get("/ingest/status").json()["id"], job_id)


class IngestJobRunTests(IngestJobTestCase):
    def _wait_until_finished(self, job_id, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = database.get_job(job_id)
            if job["state"] not in ("queued", "running"):
                return job
            time.sleep(0.02)
        self.fail("the ingest job did not finish")

    def test_the_job_reports_progress_and_returns_the_counts(self):
        def fake_ingest_all(report):
            for done in range(3):
                report(done, 3, f"Indexing file{done}.txt")
            return {"indexed": 3, "chunks": 9, "skipped": 0, "unchanged": 0, "scanned": 3}

        with (
            patch.object(rag_service, "ingest_all", side_effect=fake_ingest_all),
            patch.object(rag_service, "prune_stale", return_value=1),
            patch.object(rag_service, "invalidate_caches") as invalidate,
            TestClient(app, headers={"Authorization": f"Bearer {API_TOKEN}"}) as client,
        ):
            job = self._wait_until_finished(client.post("/ingest").json()["id"])

        self.assertEqual(job["state"], "done")
        self.assertEqual(job["result"], {"indexed": 3, "chunks": 9, "skipped": 0, "unchanged": 0, "scanned": 3, "pruned": 1})
        self.assertEqual((job["progress_current"], job["progress_total"], job["progress_message"]), (2, 3, "Indexing file2.txt"))
        invalidate.assert_called_once()

    def test_cancel_stops_the_ingestion_and_still_refreshes_search(self):
        def endless_ingest_all(report):
            done = 0
            while True:
                report(done, 10_000, "Indexing")
                done += 1
                time.sleep(0.01)

        with (
            patch.object(rag_service, "ingest_all", side_effect=endless_ingest_all),
            patch.object(rag_service, "invalidate_caches") as invalidate,
            TestClient(app, headers={"Authorization": f"Bearer {API_TOKEN}"}) as client,
        ):
            job_id = client.post("/ingest").json()["id"]
            while database.get_job(job_id)["state"] != "running":
                time.sleep(0.01)
            client.post(f"/jobs/{job_id}/cancel")
            job = self._wait_until_finished(job_id)

        self.assertEqual(job["state"], "cancelled")
        invalidate.assert_called_once()  # files indexed before the cancel are searchable


class CancelCheckThrottleTests(IngestJobTestCase):
    def test_the_cancel_flag_is_read_at_most_once_per_interval(self):
        job_id = database.enqueue_job("anything")
        database.claim_next_job()
        now = [100.0]
        ctx = worker.JobContext(job_id, clock=lambda: now[0])

        with (
            patch.object(worker, "JOB_CANCEL_CHECK_SECONDS", 0.5),
            patch.object(database, "is_cancel_requested", return_value=False) as read,
        ):
            for _ in range(100):
                ctx.check_cancelled()
            now[0] += 0.5
            ctx.check_cancelled()

        self.assertEqual(read.call_count, 2)


if __name__ == "__main__":
    unittest.main()
