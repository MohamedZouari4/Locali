"""Tests for the file details tool (P1-E4-T6): a file's size, type, dates and page count come back; asking
about a screenshot returns its text; a file whose text can't be read still gets its metadata; the image text
is file content, so tools that change files are withheld after it; and the tool is offered in a project's
chat despite the tool cap. Uses a temporary database and folders. The OCR test needs Tesseract and the agent
test also needs Ollama, so each is skipped without them.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont
from test_integration import _ollama_ready
from test_reader import _write_pdf

from app.ai.chat import orchestrator
from app.ai.ingestion import extractors
from app.core import config
from app.core.config import MAX_TOOLS_PER_STEP
from app.db import database
from app.services import catalog_service, health_service
from app.tools import registry
from app.tools.project_tools import OCR_NOTE

SCREENSHOT_LINES = ["Invoice 4821 is due on Friday", "Total: 312 TND"]


def _ocr_ready():
    return health_service.check_ocr()["status"] == "ok", "Tesseract OCR isn't installed"


def _write_screenshot(path, lines):
    """A PNG with each line in large black text, like a screenshot of a message."""
    image = Image.new("RGB", (900, 100 * len(lines) + 40), "white")
    draw = ImageDraw.Draw(image)
    for number, line in enumerate(lines):
        draw.text((30, 30 + 80 * number), line, fill="black", font=ImageFont.load_default(size=40))
    image.save(path)


class FileDetailsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = os.path.realpath(tempfile.mkdtemp(prefix="file_details_test_"))
        self.docs = os.path.join(self.tmpdir, "Thesis")
        os.makedirs(self.docs)
        self._patches = [
            patch.object(database, "DB_PATH", os.path.join(self.tmpdir, "assistant_test.db")),
            patch.object(database, "_initialized", False),
            # The temp folder may sit under AppData, which is never catalogued; tests set their own rules.
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

    def _scan(self):
        catalog_service.catalog_project(database.get_project(self.project_id))

    def _details(self, **arguments):
        """The tool's result through the registry, as the chat model gets it."""
        return registry.run("file_details", arguments, {"file_details"}, self.project_id)


class AcceptanceTests(FileDetailsTestCase):
    def test_a_pdf_gives_its_size_dates_type_and_page_count(self):
        _write_pdf(os.path.join(self.docs, "report.pdf"), ["One", "Two", "Three"])
        self._scan()

        result = self._details(path="report.pdf")

        self.assertTrue(result["ok"], result)
        details = result["result"]
        self.assertEqual((details["name"], details["type"], details["kind"], details["pages"]), ("report.pdf", "pdf", "document", 3))
        self.assertEqual(details["size_bytes"], os.path.getsize(os.path.join(self.docs, "report.pdf")))
        self.assertRegex(details["modified"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertNotIn("extension", details)
        self.assertNotIn("ocr_text", details)

    def test_asking_about_a_screenshot_returns_its_text(self):
        _write_screenshot(os.path.join(self.docs, "shot.png"), ["placeholder"])
        self._scan()

        # OCR itself is stubbed so the test runs where Tesseract isn't installed, such as CI.
        with patch.object(extractors.pytesseract, "image_to_string", return_value="Invoice 4821 is due on Friday\n"):
            result = self._details(path="shot.png")

        self.assertTrue(result["ok"], result)
        details = result["result"]
        self.assertEqual((details["type"], details["kind"]), ("png", "image"))
        self.assertIn("Invoice 4821", details["ocr_text"])
        self.assertEqual(details["note"], OCR_NOTE)
        self.assertEqual(list(details)[-1], "ocr_text")

    def test_a_file_without_text_still_gets_its_metadata(self):
        # A .zip would be skipped by the catalog; a .pptx is catalogued but has no reader.
        with open(os.path.join(self.docs, "slides.pptx"), "wb") as f:
            f.write(b"PK\x03\x04\x00\x00\x00\x00")
        self._scan()

        result = self._details(path="slides.pptx")

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["size_bytes"], 8)
        self.assertEqual(result["result"]["text_unavailable"]["code"], "unsupported_type")

    def test_an_unknown_file_is_not_found(self):
        self._scan()

        result = self._details(path="missing.png")

        self.assertEqual(result["error"]["code"], "not_found")

    def test_the_image_text_is_file_content_so_write_tools_are_withheld(self):
        card, _function = registry.TOOLS["file_details"]

        self.assertTrue(card.returns_content)

    def test_it_is_offered_in_a_projects_chat(self):
        offered = {card.name for card in registry.offer(MAX_TOOLS_PER_STEP, self.project_id)}

        self.assertIn("file_details", offered)


@unittest.skipUnless(*_ocr_ready())
class OcrTests(FileDetailsTestCase):
    def test_a_real_screenshot_is_read_with_tesseract(self):
        _write_screenshot(os.path.join(self.docs, "shot.png"), SCREENSHOT_LINES)
        self._scan()

        details = self._details(path="shot.png")["result"]

        self.assertIn("Invoice 4821", details["ocr_text"])
        self.assertIn("312", details["ocr_text"])


@unittest.skipUnless(*_ollama_ready())
@unittest.skipUnless(*_ocr_ready())
class AgentTests(FileDetailsTestCase):
    def test_asking_about_a_screenshot_returns_its_text(self):
        _write_screenshot(os.path.join(self.docs, "shot.png"), SCREENSHOT_LINES)
        self._scan()

        with patch.object(registry, "run", wraps=registry.run) as run:
            answer, _sources, _used_tools = orchestrator.ask("What does the screenshot shot.png say?", project_id=self.project_id)

        names = [call.args[0] for call in run.call_args_list]
        self.assertTrue({"file_details", "read_file"} & set(names), f"no tool read the image: {names}")
        self.assertIn("4821", answer)


if __name__ == "__main__":
    unittest.main()
