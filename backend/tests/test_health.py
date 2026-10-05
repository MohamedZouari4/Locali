"""Tests for the health checks and friendly errors, including the acceptance criteria: with Ollama
stopped, chat says "Model runtime not running — start it" instead of an error trace, and a missing
model is named exactly. Ollama is replaced by mocks, so these run without it (and in CI).
"""

import os
import shutil
import tempfile
import unittest
from collections import namedtuple
from unittest.mock import MagicMock, patch

import requests
from fastapi.testclient import TestClient

from app.ai.chat import orchestrator
from app.api.main import app
from app.chat_events import CHAT_SUBPROTOCOL
from app.core.config import CHAT_MODEL, EMBEDDING_MODEL, OLLAMA_URL
from app.core.friendly_errors import describe_error
from app.core.security import API_TOKEN
from app.db import database
from app.jobs import worker
from app.services import health_service

DiskUsage = namedtuple("DiskUsage", "total used free")


def _connection_error(path="/api/chat"):
    return requests.ConnectionError("connection refused", request=requests.Request("POST", f"{OLLAMA_URL}{path}").prepare())


def _not_found(path):
    response = requests.Response()
    response.status_code = 404
    response.url = f"{OLLAMA_URL}{path}"
    return requests.HTTPError("404 Client Error", response=response, request=requests.Request("POST", response.url).prepare())


def _tags(*names):
    reply = MagicMock()
    reply.json.return_value = {"models": [{"name": name} for name in names]}
    return reply


class ModelCheckTests(unittest.TestCase):
    def _models(self, **kwargs):
        with patch.object(health_service.requests, "get", **kwargs):
            return {check["id"]: check for check in health_service.check_models()}

    def test_everything_installed_is_ok(self):
        checks = self._models(return_value=_tags(CHAT_MODEL, EMBEDDING_MODEL))

        self.assertEqual({check["status"] for check in checks.values()}, {"ok"})

    def test_a_stopped_runtime_says_to_start_it(self):
        checks = self._models(side_effect=requests.ConnectionError("refused"))

        runtime = checks["model_runtime"]
        self.assertEqual((runtime["status"], runtime["title"]), ("error", "Model runtime not running — start it"))
        self.assertIn("ollama serve", runtime["fix"])
        self.assertEqual((checks["chat_model"]["status"], checks["embedding_model"]["status"]), ("unknown", "unknown"))

    def test_a_missing_model_is_named_exactly(self):
        checks = self._models(return_value=_tags(EMBEDDING_MODEL))

        chat = checks["chat_model"]
        self.assertEqual(
            (chat["status"], chat["title"], chat["fix"]), ("error", f"Model {CHAT_MODEL} isn't installed", f"Run: ollama pull {CHAT_MODEL}")
        )
        self.assertEqual(checks["embedding_model"]["status"], "ok")

    def test_a_name_without_a_tag_matches_latest(self):
        self.assertTrue(health_service._is_installed("nomic-embed-text", {"nomic-embed-text:latest"}))
        self.assertFalse(health_service._is_installed("qwen3:4b", {"qwen3:4b-instruct"}))


class OtherCheckTests(unittest.TestCase):
    def test_low_disk_space_is_a_warning(self):
        with patch.object(health_service.shutil, "disk_usage", return_value=DiskUsage(0, 0, 100 * 1024**2)):
            check = health_service.check_disk()
        self.assertEqual((check["status"], check["title"]), ("warning", "Low disk space"))
        self.assertIn("Only 100 MB free", check["detail"])

    def test_missing_ocr_is_a_warning_with_the_path_to_fix(self):
        with patch.object(health_service, "TESSERACT_PATH", "Z:/no/tesseract.exe"):
            check = health_service.check_ocr()
        self.assertEqual((check["status"], check["title"]), ("warning", "OCR not available"))
        self.assertIn("Z:/no/tesseract.exe", check["fix"])

    def test_the_overall_status_is_the_worst_check(self):
        warning = {"id": "x", "status": "warning", "title": "x", "detail": None, "fix": None}
        ok = dict(warning, status="ok")
        with (
            patch.object(health_service, "check_models", return_value=[ok]),
            patch.object(health_service, "check_disk", return_value=warning),
            patch.object(health_service, "check_ocr", return_value=ok),
        ):
            self.assertEqual(health_service.run_checks()["status"], "warning")


class HealthRouteTests(unittest.TestCase):
    def test_checks_need_the_token_but_liveness_does_not(self):
        self.assertEqual(TestClient(app).get("/health/checks").status_code, 401)
        self.assertEqual(TestClient(app).get("/health").json(), {"status": "ok"})

    def test_checks_return_every_check(self):
        with patch.object(health_service.requests, "get", side_effect=requests.ConnectionError("refused")):
            report = TestClient(app, headers={"Authorization": f"Bearer {API_TOKEN}"}).get("/health/checks").json()

        self.assertEqual(report["status"], "error")
        self.assertEqual(
            [check["id"] for check in report["checks"]], ["model_runtime", "chat_model", "embedding_model", "disk_space", "ocr"]
        )


class DescribeErrorTests(unittest.TestCase):
    def test_runtime_down(self):
        self.assertIn("Model runtime not running — start it", describe_error(_connection_error()))

    def test_missing_chat_and_embedding_models(self):
        self.assertIn(f"ollama pull {CHAT_MODEL}", describe_error(_not_found("/api/chat")))
        self.assertIn(f"ollama pull {EMBEDDING_MODEL}", describe_error(_not_found("/api/embed")))

    def test_the_cause_chain_is_followed(self):
        try:
            try:
                raise _not_found("/api/embed")
            except requests.HTTPError as cause:
                raise RuntimeError("embed_batch() failed after 3 attempts") from cause
        except RuntimeError as error:
            self.assertIn(f"Model {EMBEDDING_MODEL} isn't installed", describe_error(error))

    def test_other_errors_are_left_alone(self):
        self.assertIsNone(describe_error(ValueError("bad input")))
        other_host = requests.ConnectionError("refused", request=requests.Request("GET", "http://example.invalid/").prepare())
        self.assertIsNone(describe_error(other_host))


class FriendlyErrorsInUseTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="health_test_")
        self._patches = [
            patch.object(database, "DB_PATH", os.path.join(self.tmpdir, "assistant_test.db")),
            patch.object(database, "_initialized", False),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _chat_error(self, ollama_error):
        client = TestClient(app)
        with patch.object(orchestrator.requests, "post", side_effect=ollama_error):
            with client.websocket_connect(
                "/chat/stream", headers={"authorization": f"Bearer {API_TOKEN}"}, subprotocols=[CHAT_SUBPROTOCOL]
            ) as ws:
                ws.send_json({"message": "hello", "use_docs": False})
                event = ws.receive_json()
        self.assertEqual(event["type"], "error")
        return event["text"]

    def test_chat_with_ollama_stopped_says_to_start_it(self):
        text = self._chat_error(_connection_error())

        self.assertTrue(text.startswith("Model runtime not running — start it."), text)
        self.assertNotIn("HTTPConnectionPool", text)

    def test_chat_with_the_model_missing_names_it(self):
        self.assertIn(f"ollama pull {CHAT_MODEL}", self._chat_error(_not_found("/api/chat")))

    def test_a_failed_job_gets_the_friendly_message(self):
        def needs_ollama(params, ctx):
            raise RuntimeError("embed_batch() failed after 3 attempts") from _connection_error("/api/embed")

        job_id = database.enqueue_job("needs_ollama")
        with patch.dict(worker.HANDLERS, {"needs_ollama": needs_ollama}), self.assertLogs("app.jobs.worker", level="ERROR"):
            worker.run_job(database.claim_next_job())

        self.assertTrue(database.get_job(job_id)["error"].startswith("Model runtime not running — start it."))


if __name__ == "__main__":
    unittest.main()
