"""Tests for multilingual search terms (P1-E3-T6): Arabic, accented and unspaced scripts are split and
folded the same way for documents and queries, English terms are unchanged, and BM25 keyword search
finds an Arabic document from an Arabic question.
"""

import unittest
from unittest.mock import MagicMock, patch

from app.ai.retrieval import sparse_retriever
from app.core.text_terms import terms, tokenize


class TermTests(unittest.TestCase):
    def test_an_accented_word_stays_one_term(self):
        self.assertEqual(tokenize("Réunion du conseil"), ["reunion", "du", "conseil"])

    def test_english_terms_are_unchanged(self):
        self.assertEqual(tokenize("The Quarterly tax_report, v2!"), ["the", "quarterly", "tax", "report", "v2"])

    def test_arabic_marks_and_letter_forms_are_folded(self):
        self.assertEqual(tokenize("اَلْمُدِيرُ أحمد"), ["المدير", "احمد"])
        self.assertEqual(tokenize("إلى آخر مدرسة"), tokenize("الي اخر مدرسه"))
        self.assertEqual(tokenize("كتـــاب ٢٠٢٦"), ["كتاب", "2026"])

    def test_other_scripts_keep_whole_words(self):
        self.assertEqual(len(tokenize("हिंदी भाषा")), 2)
        self.assertEqual(tokenize("Москва ЁЛКА"), ["москва", "елка"])

    def test_unspaced_scripts_are_split_into_pairs(self):
        self.assertEqual(tokenize("会议记录。"), ["会议", "议记", "记录"])
        self.assertEqual(tokenize("タワー"), ["タワ", "ワー"])

    def test_each_term_points_at_the_text_it_came_from(self):
        text = "Le réunion"
        self.assertEqual([text[start:end] for _, start, end in terms(text)], ["Le", "réunion"])


class Bm25Tests(unittest.TestCase):
    def _search(self, docs, query):
        """The id of the best BM25 chunk for `query`, over a fake collection holding `docs`."""
        ids = [f"c{n}" for n in range(len(docs))]
        collection = MagicMock()
        collection.count.return_value = len(docs)
        collection.get.return_value = {"ids": ids, "documents": docs, "metadatas": [{"source": f"{i}.txt"} for i in ids]}
        sparse_retriever.invalidate_caches()
        with patch.object(sparse_retriever, "get_collection", return_value=collection):
            ranked, _, _ = sparse_retriever.bm25_search(query, pool_size=1)
        sparse_retriever.invalidate_caches()
        return ranked

    def test_an_arabic_question_finds_the_arabic_document(self):
        docs = [
            "The quarterly tax report is late.",
            "اجتمع المُديرُ مع الموظفين لمناقشة الميزانيّة السنوية.",
            "La réunion du conseil a lieu lundi.",
        ]
        self.assertEqual(self._search(docs, "ما هي الميزانية السنوية؟"), ["c1"])
        self.assertEqual(self._search(docs, "réunion"), ["c2"])
        self.assertEqual(self._search(docs, "tax report"), ["c0"])


if __name__ == "__main__":
    unittest.main()
