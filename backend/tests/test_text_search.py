"""Tests for full-text search over the text cache (P1-E3-T3): a phrase finds the right file and page,
fast on a medium project; the index follows the cache as files change and are pruned; each project
only sees its own files; typed punctuation is searched as words; and Arabic, accented and Chinese words are
found (P1-E3-T6). Uses a temporary database and folders.
"""

import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

from test_reader import _write_pdf

from app.ai.ingestion.extractors import EXTRACTOR_VERSION
from app.core import config
from app.db import database
from app.services import catalog_service, text_cache_service, text_search_service


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class TextSearchTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="text_search_test_")
        self.docs = os.path.join(self.tmpdir, "docs")
        os.makedirs(self.docs)
        self._patches = [
            patch.object(database, "DB_PATH", os.path.join(self.tmpdir, "assistant_test.db")),
            patch.object(database, "_initialized", False),
            # The temp folder may sit under AppData, which is never indexed; tests set their own rules.
            patch.object(config, "SYSTEM_EXCLUDE", [os.path.join(self.tmpdir, "Windows")]),
            patch.object(config, "PRIVACY_EXCLUDE", ["Google/Chrome"]),
            patch.object(config, "IGNORE_DIRS", {".git", "node_modules"}),
        ]
        for p in self._patches:
            p.start()
        self.project_id = database.create_project("Thesis", folders=[(self.docs, "read")])["id"]

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _read_all(self, project_id=None):
        """Scans the project and reads every catalogued file into the text cache."""
        project_id = project_id or self.project_id
        catalog_service.catalog_project(database.get_project(project_id))
        for file in database.list_catalog_files(project_id):
            text_cache_service.read_text(project_id, file["id"])

    def _found(self, query, project_id=None):
        """(name, page) of each hit, best first."""
        return [(hit["name"], hit["page"]) for hit in text_search_service.search(project_id or self.project_id, query)]


class AcceptanceTests(TextSearchTestCase):
    def test_a_phrase_finds_the_right_file_and_page(self):
        _write_pdf(os.path.join(self.docs, "report.pdf"), ["Introduction", "The quarterly tax report is late", "Summary"])
        _write_pdf(os.path.join(self.docs, "notes.pdf"), ["A report on tax and quarterly plans"])
        self._read_all()

        hits = text_search_service.search(self.project_id, '"quarterly tax report"')

        self.assertEqual([(hit["name"], hit["page"]) for hit in hits], [("report.pdf", 2)])
        self.assertEqual(hits[0]["snippet"], "The **quarterly tax report** is late")
        self.assertEqual(hits[0]["path"], os.path.join(self.docs, "report.pdf"))

    def test_a_phrase_is_found_in_under_a_second_on_a_medium_project(self):
        # 300 PDFs of 10 pages of 200 words each (3,000 pages), cached directly so no files are written.
        words = [f"word{n}" for n in range(5000)]
        files = []
        for number in range(300):
            pages = [" ".join(words[(number * 37 + page * 11 + i) % len(words)] for i in range(200)) for page in range(10)]
            if number == 150:
                pages[6] += " the quarterly tax report"
            database.save_cached_text(f"hash{number}", "pdf", EXTRACTOR_VERSION, "page", pages)
            files.append(
                {
                    "file_key": f"path:{number}",
                    "path": os.path.join(self.docs, f"file{number}.pdf"),
                    "name": f"file{number}.pdf",
                    "extension": "pdf",
                    "size": 1,
                    "file_created_at": None,
                    "file_modified_at": "2026-10-13 10:00:00",
                    "content_hash": None,
                }
            )
        database.save_catalog_scan(self.project_id, [], files, [])
        for file in database.list_catalog_files(self.project_id):
            database.set_catalog_text_hash(file["id"], file["name"].replace("file", "hash").removesuffix(".pdf"))

        started = time.perf_counter()
        found = self._found('"quarterly tax report"')
        elapsed = time.perf_counter() - started

        self.assertEqual(found, [("file150.pdf", 7)])
        self.assertLess(elapsed, 1.0)


class IndexFollowsCacheTests(TextSearchTestCase):
    def test_a_changed_file_is_found_by_its_new_text_once_read_again(self):
        path = os.path.join(self.docs, "notes.md")
        _write(path, "first draft about owls")
        self._read_all()

        _write(path, "second draft about foxes")
        self._read_all()

        self.assertEqual(self._found("owls"), [])
        self.assertEqual(self._found("foxes"), [("notes.md", None)])

    def test_a_deleted_file_leaves_the_index_after_the_next_scan(self):
        path = os.path.join(self.docs, "old.txt")
        _write(path, "soon gone")
        self._read_all()

        os.remove(path)
        catalog_service.catalog_project(database.get_project(self.project_id))

        self.assertEqual(self._found("gone"), [])
        conn = database.get_connection()
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM text_search WHERE text_search MATCH 'gone'").fetchone()[0], 0)
        finally:
            conn.close()

    def test_words_match_in_any_order_whatever_their_case_and_accents(self):
        _write(os.path.join(self.docs, "cv.txt"), "Mon Résumé pour le poste")
        self._read_all()

        self.assertEqual(self._found("POSTE resume"), [("cv.txt", None)])
        self.assertEqual(self._found('"poste resume"'), [])


class LooseMatchTests(TextSearchTestCase):
    """The LangGraph spike (P1-E5-T1): models search with their own words, so exact whole-word matching on one
    page missed facts that were in the files."""

    def test_a_word_finds_longer_words_it_begins(self):
        _write_pdf(os.path.join(self.docs, "report.pdf"), ["Introduction", "Risks: sensor 7 fails in heavy rain."])
        self._read_all()

        self.assertEqual(self._found("risk"), [("report.pdf", 2)])
        self.assertEqual(text_search_service.search(self.project_id, "risk")[0]["snippet"], "**Risks**: sensor 7 fails in heavy rain.")

    def test_without_a_page_holding_every_word_the_pages_holding_some_are_found(self):
        _write_pdf(os.path.join(self.docs, "report.pdf"), ["Greenhouse Q3 report", "The quarterly budget is 48,500 TND."])
        self._read_all()

        hits = text_search_service.search(self.project_id, "Greenhouse budget")

        self.assertEqual(sorted(hit["page"] for hit in hits), [1, 2])
        self.assertFalse(hits[0]["all_words"])
        self.assertTrue(text_search_service.search(self.project_id, "quarterly budget")[0]["all_words"])

    def test_a_quoted_phrase_stays_required_when_the_other_words_are_loosened(self):
        _write(os.path.join(self.docs, "a.txt"), "the tax report is late")
        _write(os.path.join(self.docs, "b.txt"), "the budget is late")
        self._read_all()

        self.assertEqual(self._found('"tax report" budget'), [("a.txt", None)])
        self.assertEqual(self._found('"report tax"'), [])

    def test_a_question_with_a_file_name_and_several_words_is_searched(self):
        """A file name becomes a phrase; with several loose words the fallback once failed with an FTS5 syntax error."""
        _write(os.path.join(self.docs, "setup.txt"), "Set the reading interval to 15 minutes in config.ini.")
        self._read_all()

        self.assertEqual(self._found("What reading interval should be set in config.ini?"), [("setup.txt", None)])
        self.assertEqual(self._found("Which interval does config.ini use for sensors?"), [("setup.txt", None)])

    def test_a_file_name_in_the_question_is_not_required_in_the_text(self):
        _write(os.path.join(self.docs, "pump.txt"), "def start_pump(seconds=90): starts the backup pump")
        self._read_all()

        self.assertEqual(self._found("What does the function in pump.py do?"), [("pump.txt", None)])

    def test_an_arabic_word_finds_it_with_a_prefix(self):
        _write(os.path.join(self.docs, "ideas.txt"), "فكرة: إضافة حساس للحرارة في البيت البلاستيكي.")
        self._read_all()

        self.assertEqual(self._found("الحرارة"), [("ideas.txt", None)])


class ScopeTests(TextSearchTestCase):
    def test_another_projects_files_are_not_found(self):
        other_docs = os.path.join(self.tmpdir, "taxes")
        os.makedirs(other_docs)
        _write(os.path.join(other_docs, "return.txt"), "private tax return")
        other_id = database.create_project("Taxes", folders=[(other_docs, "read")])["id"]
        self._read_all(other_id)

        self.assertEqual(self._found("tax"), [])
        self.assertEqual(self._found("tax", other_id), [("return.txt", None)])

    def test_query_syntax_and_stray_quotes_are_searched_as_words(self):
        _write(os.path.join(self.docs, "code.txt"), "C++ and Rust NEAR each other")
        self._read_all()

        for query in ["NEAR(", '"Rust', "C++ AND", "*", "-", 'a"b']:
            text_search_service.search(self.project_id, query)  # none of these raise
        self.assertEqual(self._found("rust near"), [("code.txt", None)])
        self.assertEqual(self._found("   "), [])


class MultilingualTests(TextSearchTestCase):
    """P1-E3-T6: the full-text index splits and folds words like keyword search, in any script."""

    def test_an_arabic_question_finds_the_arabic_document(self):
        _write(os.path.join(self.docs, "budget.txt"), "اجتمع المُديرُ مع الموظفين لمناقشة الميزانيّة السنوية.")
        _write(os.path.join(self.docs, "notes.txt"), "The annual budget meeting.")
        self._read_all()

        hits = text_search_service.search(self.project_id, "الميزانية السنوية")

        self.assertEqual([hit["name"] for hit in hits], ["budget.txt"])
        self.assertEqual(hits[0]["snippet"], "اجتمع المُديرُ مع الموظفين لمناقشة **الميزانيّة السنوية**.")

    def test_accents_and_chinese_words_are_found(self):
        _write(os.path.join(self.docs, "fr.txt"), "La réunion du conseil")
        _write(os.path.join(self.docs, "zh.txt"), "会议记录在这里")
        self._read_all()

        self.assertEqual(self._found("reunion"), [("fr.txt", None)])
        self.assertEqual(self._found("Réunion"), [("fr.txt", None)])
        self.assertEqual(self._found("记录"), [("zh.txt", None)])


if __name__ == "__main__":
    unittest.main()
