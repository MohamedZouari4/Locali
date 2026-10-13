"""Tests for redacting personal data and secrets (P1-E3-T4): sample secrets and personal data are replaced
before text is cached or indexed, so the model never sees them, whether through reading a file, full-text
search or the vector index; and text cached under older redaction rules is extracted again and pruned.
Uses a temporary database, folders and index, and fake embeddings, so no Ollama is needed.

The sample secrets are built from pieces, so secret scanners don't take this file for a leak.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.ai.ingestion import pipeline, store
from app.ai.ingestion.extractors import EXTRACTOR_VERSION
from app.ai.ingestion.redaction import classify_sensitivity, redact_pii
from app.ai.retrieval import sparse_retriever
from app.core import config
from app.db import database
from app.services import catalog_service, reader_service, text_cache_service, text_search_service

# (a line as it might appear in a file, the part of it that must never reach the model)
SAMPLES = {
    "email": ("Write to alice.martin@example.com today", "alice.martin@" + "example.com"),
    "phone": ("Call 555-123-4567 after six", "555-123-" + "4567"),
    "ssn": ("SSN 123-45-6789", "123-45-" + "6789"),
    "credit card": ("Card 4111 1111 1111 1111", "4111 1111 " + "1111 1111"),
    "aws key": ("aws_access_key_id = AKIA" + "IOSFODNN7EXAMPLE", "AKIA" + "IOSFODNN7EXAMPLE"),
    "aws secret": ("aws_secret_access_key = " + "wJalrXUtnFEMI/K7MDENG/" + "bPxRfiCYEXAMPLEKEY", "bPxRfiCY" + "EXAMPLEKEY"),
    "github token": ("token ghp_" + "16C7e42F292c6912E7710c838347Ae178B4a", "16C7e42F292c" + "6912E7710c838347Ae178B4a"),
    "jwt": ("Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0", "eyJzdWIiOiIx" + "MjM0NTY3ODkwIn0"),
    "private key": ("MIIEowIBAAKCAQEA0Z3VS5JJcds3xfn/" + "ygWyF8PbnGy0AHB7MaLE2qwbxGUw1ZPq", "ygWyF8PbnGy0" + "AHB7MaLE2qwbxGUw1ZPq"),
    "password": ("password = " + "hunter2", "hunter" + "2"),
    "env password": ("DB_PASSWORD=" + "Summer2026!", "Summer" + "2026!"),
    "json api key": ('"api_key": "' + 'k3y-not-random"', "k3y-not-" + "random"),
}


class RuleTests(unittest.TestCase):
    def test_every_sample_secret_and_personal_detail_is_redacted(self):
        for name, (line, secret) in SAMPLES.items():
            with self.subTest(name):
                self.assertNotIn(secret, redact_pii(line)[0])

    def test_an_assigned_secret_keeps_its_key_name(self):
        self.assertEqual(redact_pii("DB_PASSWORD=" + "Summer2026!")[0], "DB_PASSWORD=[REDACTED_SECRET]")
        self.assertEqual(redact_pii('"password": "correct horse"')[0], '"password": [REDACTED_SECRET]')

    def test_code_that_only_mentions_tokens_or_passwords_is_left_alone(self):
        for line in [
            "max_tokens = 512",
            "tokens = text.split()",
            "token_count = 3",
            "if token == expected:",
            "The password is in the vault.",
        ]:
            with self.subTest(line):
                self.assertEqual(redact_pii(line)[0], line)

    def test_an_assigned_secret_makes_the_text_highly_sensitive(self):
        self.assertEqual(classify_sensitivity(redact_pii("password = " + "hunter2")[1]), "high")


class ModelContextTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="redaction_test_")
        self.docs = os.path.join(self.tmpdir, "docs")
        os.makedirs(self.docs)
        self.path = os.path.join(self.docs, "notes.txt")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("\n".join(line for line, _secret in SAMPLES.values()))
        self._patches = [
            patch.object(database, "DB_PATH", os.path.join(self.tmpdir, "assistant_test.db")),
            patch.object(database, "_initialized", False),
            patch.object(config, "VECTOR_DIR", os.path.join(self.tmpdir, "vector_store")),
            # The temp folder may sit under AppData, which is never indexed; tests set their own rules.
            patch.object(config, "SYSTEM_EXCLUDE", [os.path.join(self.tmpdir, "Windows")]),
            patch.object(config, "PRIVACY_EXCLUDE", ["Google/Chrome"]),
            patch.object(config, "IGNORE_DIRS", {".git", "node_modules"}),
            patch.object(store, "embed_batch", lambda texts: [[0.1, 0.2] for _ in texts]),
        ]
        for p in self._patches:
            p.start()
        store.close_collection()
        sparse_retriever.invalidate_caches()
        self.project_id = database.create_project("Thesis", folders=[(self.docs, "read")])["id"]
        catalog_service.catalog_project(database.get_project(self.project_id))
        self.file_id = database.list_catalog_files(self.project_id)[0]["id"]

    def tearDown(self):
        for p in self._patches:
            p.stop()
        store.close_collection()
        sparse_retriever.invalidate_caches()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _cached_text(self):
        """All the text the text cache holds, for every file and version."""
        conn = database.get_connection()
        try:
            return "\n".join(row[0] for row in conn.execute("SELECT text FROM text_cache_parts"))
        finally:
            conn.close()

    def _indexed(self, words):
        """Whether the full-text index holds these words, in any file and version."""
        conn = database.get_connection()
        try:
            match = text_search_service._match_expression(words)
            return conn.execute("SELECT COUNT(*) FROM text_search WHERE text_search MATCH ?", (match,)).fetchone()[0] > 0
        finally:
            conn.close()


class AcceptanceTests(ModelContextTestCase):
    def test_sample_secrets_never_reach_the_model_through_reading_or_search(self):
        read = reader_service.read_part(self.project_id, self.file_id)["text"]
        snippets = " ".join(hit["snippet"] for hit in text_search_service.search(self.project_id, "password token key"))

        for name, (_line, secret) in SAMPLES.items():
            with self.subTest(name):
                self.assertNotIn(secret, read)
                self.assertNotIn(secret, snippets)
                self.assertNotIn(secret, self._cached_text())
                self.assertFalse(self._indexed(f'"{secret}"'))

    def test_sample_secrets_never_reach_the_model_through_the_vector_index(self):
        self.assertEqual(pipeline.index_file(self.path)[0], "indexed")

        documents = "\n".join(store.get_collection().get(include=["documents"])["documents"])
        for name, (_line, secret) in SAMPLES.items():
            with self.subTest(name):
                self.assertNotIn(secret, documents)


class OldRulesTests(ModelContextTestCase):
    def _cache_under_old_rules(self):
        """Caches the file's text as an older Locali would have: under the previous version, with the
        assigned password still in it."""
        content_hash = pipeline.file_hash(self.path)
        database.set_catalog_text_hash(self.file_id, content_hash)
        database.save_cached_text(content_hash, "txt", EXTRACTOR_VERSION - 1, "section", ["password = " + "hunter2"])

    def test_text_cached_under_older_rules_is_never_served(self):
        self._cache_under_old_rules()

        text = text_cache_service.read_text(self.project_id, self.file_id)["parts"][0]

        self.assertIn("password = [REDACTED_SECRET]", text)
        self.assertEqual(text_search_service.search(self.project_id, "hunter2"), [])

    def test_text_cached_under_older_rules_is_pruned_after_the_next_scan(self):
        self._cache_under_old_rules()
        text_cache_service.read_text(self.project_id, self.file_id)

        catalog_service.catalog_project(database.get_project(self.project_id))

        self.assertNotIn("hunter" + "2", self._cached_text())
        self.assertFalse(self._indexed("hunter" + "2"))


if __name__ == "__main__":
    unittest.main()
