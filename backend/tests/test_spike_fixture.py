"""Checks the LangGraph spike's question set (P1-E5-T1) without a model: there are 30 questions with unique
ids, and every expected fact is really in the file the question is about, read through the text cache as the
tools read it. The fixture builds on a temporary database. A failed spike answer is then the model's fault,
not the data's."""

import os
import unittest

import yaml

from app.db import database
from app.services import text_cache_service
from scripts.spike.fixture import QUESTIONS, spike_project


class SpikeQuestionTests(unittest.TestCase):
    def setUp(self):
        self.questions = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))

    def test_there_are_thirty_questions_with_unique_ids(self):
        self.assertEqual(len(self.questions), 30)
        self.assertEqual(len({question["id"] for question in self.questions}), 30)

    def test_every_expected_fact_is_in_its_source_file(self):
        with spike_project() as (project_id, root):
            files = {os.path.relpath(file["path"], root).replace("\\", "/"): file["id"] for file in database.list_catalog_files(project_id)}
            for question in (question for question in self.questions if question.get("source")):
                with self.subTest(question["id"]):
                    text = "\n".join(text_cache_service.read_text(project_id, files[question["source"]])["parts"]).casefold()
                    self.assertTrue(any(word.casefold() in text for word in question["answer"]), question["question"])


if __name__ == "__main__":
    unittest.main()
