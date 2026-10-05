"""Tests for the job routes and the /jobs/events WebSocket, including the two acceptance criteria:
progress events arrive while a long job runs, and Cancel stops a running job within a few seconds.
Uses a temporary database and the demo job kind.
"""

import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api.main import app
from app.core.security import API_TOKEN
from app.db import database
from app.job_events import JOB_SUBPROTOCOL, job_event_adapter
from app.jobs import demo, worker


def _headers():
    # A fresh dict per connection: websocket_connect writes the subprotocol into the dict it gets.
    return {"authorization": f"Bearer {API_TOKEN}"}


class JobRoutesTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="job_routes_test_")
        self._patches = [
            patch.object(database, "DB_PATH", os.path.join(self.tmpdir, "assistant_test.db")),
            patch.object(database, "_initialized", False),
            patch.dict(worker.HANDLERS, clear=True),
            patch.object(worker, "JOB_PROGRESS_INTERVAL_SECONDS", 0),
            patch("app.job_events.JOB_EVENTS_POLL_SECONDS", 0.05),
        ]
        for p in self._patches:
            p.start()
        demo.register()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class JobRouteTests(JobRoutesTestCase):
    # Without `with TestClient(app)` the worker doesn't start, so started jobs stay queued.
    def setUp(self):
        super().setUp()
        self.client = TestClient(app, headers=_headers())

    def test_start_queues_a_job(self):
        response = self.client.post("/jobs", json={"kind": "demo", "params": {"steps": 3}})

        self.assertEqual(response.status_code, 202)
        job = response.json()
        self.assertEqual((job["kind"], job["state"], job["params"], job["project"]), ("demo", "queued", {"steps": 3}, "default"))

    def test_an_unknown_kind_is_refused(self):
        response = self.client.post("/jobs", json={"kind": "rm -rf"})

        self.assertEqual(response.status_code, 422)
        self.assertIn("Unknown job kind 'rm -rf'. Available: demo", response.json()["detail"])

    def test_get_returns_the_job_or_404(self):
        job_id = self.client.post("/jobs", json={"kind": "demo"}).json()["id"]

        self.assertEqual(self.client.get(f"/jobs/{job_id}").json()["id"], job_id)
        self.assertEqual(self.client.get("/jobs/missing").status_code, 404)

    def test_list_is_newest_first_and_filters_by_state(self):
        first = self.client.post("/jobs", json={"kind": "demo"}).json()["id"]
        second = self.client.post("/jobs", json={"kind": "demo"}).json()["id"]
        self.client.post(f"/jobs/{first}/cancel")

        self.assertEqual([job["id"] for job in self.client.get("/jobs").json()], [second, first])
        self.assertEqual([job["id"] for job in self.client.get("/jobs?state=queued&state=running").json()], [second])

    def test_cancel_cancels_a_queued_job_and_404s_an_unknown_one(self):
        job_id = self.client.post("/jobs", json={"kind": "demo"}).json()["id"]

        self.assertEqual(self.client.post(f"/jobs/{job_id}/cancel").json()["state"], "cancelled")
        self.assertEqual(self.client.post("/jobs/missing/cancel").status_code, 404)

    def test_routes_require_the_token(self):
        self.assertEqual(TestClient(app).get("/jobs").status_code, 401)

    def test_openapi_documents_the_routes_and_the_event(self):
        spec = self.client.get("/openapi.json").json()

        self.assertEqual(set(spec["paths"]["/jobs"]), {"get", "post"})
        self.assertIn("/jobs/{job_id}/cancel", spec["paths"])
        self.assertEqual(spec["x-websockets"]["/jobs/events"]["subprotocol"], JOB_SUBPROTOCOL)
        self.assertIn("type", spec["components"]["schemas"]["JobEvent"]["required"])


class JobEventTests(JobRoutesTestCase):
    def _events_until(self, ws, job_id, states):
        # Collects the events for `job_id` until it reaches one of `states`.
        events = []
        while True:
            event = ws.receive_json()
            job_event_adapter.validate_python(event)  # every event matches the documented contract
            if event["job"]["id"] == job_id:
                events.append(event["job"])
                if event["job"]["state"] in states:
                    return events

    def test_progress_events_arrive_while_a_long_job_runs(self):
        with TestClient(app, headers=_headers()) as client:
            with client.websocket_connect("/jobs/events", headers=_headers(), subprotocols=[JOB_SUBPROTOCOL]) as ws:
                self.assertEqual(ws.accepted_subprotocol, JOB_SUBPROTOCOL)
                job_id = client.post("/jobs", json={"kind": "demo", "params": {"steps": 5, "delay": 0.1}}).json()["id"]
                events = self._events_until(ws, job_id, {"done", "failed"})

        progress = [job["progress_current"] for job in events if job["state"] == "running" and job["progress_current"]]
        self.assertGreaterEqual(len(progress), 3, events)  # the bar moves in several steps
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(events[-1]["state"], "done")
        self.assertEqual(events[-1]["result"], {"steps": 5})

    def test_cancel_stops_a_running_job_within_a_few_seconds(self):
        with TestClient(app, headers=_headers()) as client:
            with client.websocket_connect("/jobs/events", headers=_headers(), subprotocols=[JOB_SUBPROTOCOL]) as ws:
                job_id = client.post("/jobs", json={"kind": "demo", "params": {"steps": 1000, "delay": 0.1}}).json()["id"]
                self._events_until(ws, job_id, {"running"})

                clicked = time.monotonic()
                self.assertTrue(client.post(f"/jobs/{job_id}/cancel").json()["cancel_requested"])
                events = self._events_until(ws, job_id, {"cancelled", "done", "failed"})
                took = time.monotonic() - clicked

        self.assertEqual(events[-1]["state"], "cancelled")
        self.assertLess(took, 3)

    def test_a_new_client_gets_the_active_jobs_first(self):
        waiting = database.enqueue_job("demo")  # queued; no worker is running in this test

        client = TestClient(app, headers=_headers())
        with client.websocket_connect("/jobs/events", headers=_headers(), subprotocols=[JOB_SUBPROTOCOL]) as ws:
            first = ws.receive_json()

        self.assertEqual((first["type"], first["job"]["id"], first["job"]["state"]), ("job", waiting, "queued"))

    def test_an_unsupported_version_is_refused(self):
        with self.assertRaises(WebSocketDisconnect) as ctx:
            with TestClient(app).websocket_connect("/jobs/events", headers=_headers(), subprotocols=["locali.jobs.v9"]):
                pass
        self.assertEqual(ctx.exception.code, 1008)


if __name__ == "__main__":
    unittest.main()
