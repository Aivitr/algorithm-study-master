"""
LSA 流水线测试 —— 从 ami_parser 迁移（负责人：陈虹宇）。

Uses a minimal toy corpus (not EN2002a) so tests are fast and
self-contained:

    "I like apples"
    "I like oranges"
    "The car is fast"
    "The vehicle moves quickly"

Vocabulary: 11 terms; 4 documents -> max feasible SVD dimension = 3.
"""

import unittest

import numpy as np

from gca_engine.core.lsa.config import LSAConfig
from gca_engine.core.lsa.lsa_model import LSAModel
from gca_engine.core.lsa.preprocessing import clean_text, tokenize
from gca_engine.core.lsa.vectorizer import TfidfStage

TOY_CORPUS = [
    "I like apples",
    "I like oranges",
    "The car is fast",
    "The vehicle moves quickly",
]


class TestPreprocessing(unittest.TestCase):
    """Preprocessing: lowercasing, punctuation, entities, edge cases."""

    def test_lowercase(self):
        self.assertEqual(clean_text("Hello World"), "hello world")

    def test_punctuation_removal(self):
        self.assertEqual(clean_text("Hello, world!"), "hello world")

    def test_html_entity_unescape(self):
        # XML entity &#39; is decoded to apostrophe, then removed as punct.
        self.assertEqual(clean_text("it&#39;s"), "it s")

    def test_none_returns_empty(self):
        self.assertEqual(clean_text(None), "")

    def test_empty_string(self):
        self.assertEqual(clean_text(""), "")

    def test_whitespace_collapse(self):
        self.assertEqual(clean_text("  a   b  "), "a b")

    def test_punctuation_only_returns_empty(self):
        self.assertEqual(clean_text("."), "")

    def test_tokenize(self):
        self.assertEqual(tokenize("One, two!"), ["one", "two"])


class TestTfidfStage(unittest.TestCase):
    """TF-IDF: vocabulary, matrix shape, determinism."""

    def test_fit_shape_and_vocab(self):
        stage = TfidfStage(LSAConfig())
        docs = [clean_text(d) for d in TOY_CORPUS]
        stats = stage.fit(docs)
        self.assertEqual(stats.matrix_shape, (4, 11))
        self.assertEqual(stats.vocabulary_size, 11)

    def test_deterministic_fit(self):
        docs = [clean_text(d) for d in TOY_CORPUS]
        m1 = TfidfStage(LSAConfig()).fit(docs)
        m2 = TfidfStage(LSAConfig()).fit(docs)
        self.assertEqual(m1.matrix_shape, m2.matrix_shape)
        self.assertEqual(m1.feature_names, m2.feature_names)

    def test_transform_requires_fit(self):
        stage = TfidfStage(LSAConfig())
        with self.assertRaises(RuntimeError):
            stage.transform(["hello"])

    def test_empty_documents(self):
        stage = TfidfStage(LSAConfig())
        docs = [clean_text(""), clean_text("hello world"), clean_text("...")]
        stats = stage.fit(docs)
        matrix = stage.transform(docs)
        self.assertEqual(matrix.shape, (3, stats.vocabulary_size))
        # Zero rows must contain no NaN.
        self.assertFalse(np.isnan(matrix.toarray()).any())

    def test_all_empty_corpus_raises(self):
        # TfidfStage receives preprocessed documents (clean_text applied);
        # an all-empty corpus must raise a clear error.
        stage = TfidfStage(LSAConfig())
        with self.assertRaises(ValueError):
            stage.fit([clean_text(""), clean_text("   "), clean_text("..")])


class TestLSAModel(unittest.TestCase):
    """End-to-end fit/transform with dimension clamping."""

    def test_dimension_clamping(self):
        """Requesting 300 dims on a 4-doc toy corpus clamps to 3."""
        model = LSAModel(LSAConfig(n_components=300))
        info = model.fit(TOY_CORPUS)
        self.assertEqual(info["requested_dimensions"], 300)
        self.assertEqual(info["actual_dimensions"], 3)  # min(4, 11) - 1
        self.assertEqual(info["max_feasible_dimensions"], 3)

    def test_vector_shape(self):
        model = LSAModel(LSAConfig(n_components=2))
        model.fit(TOY_CORPUS)
        vectors = model.transform(TOY_CORPUS)
        self.assertEqual(vectors.shape, (4, 2))

    def test_transform_new_documents(self):
        model = LSAModel(LSAConfig(n_components=2))
        model.fit(TOY_CORPUS)
        vectors = model.transform(["I like apples", "something unseen here"])
        self.assertEqual(vectors.shape, (2, 2))

    def test_transform_requires_fit(self):
        model = LSAModel(LSAConfig())
        with self.assertRaises(RuntimeError):
            model.transform(["hello"])

    def test_deterministic_output(self):
        m1 = LSAModel(LSAConfig(n_components=3))
        m1.fit(TOY_CORPUS)
        v1 = m1.transform(TOY_CORPUS)

        m2 = LSAModel(LSAConfig(n_components=3))
        m2.fit(TOY_CORPUS)
        v2 = m2.transform(TOY_CORPUS)

        self.assertTrue(np.allclose(v1, v2, rtol=1e-7, atol=1e-8))

    def test_empty_text_vectors(self):
        """Empty documents map to zero vectors; no NaN / Inf anywhere."""
        docs = ["I like apples", "", "The car is fast", "!!!", "I like oranges"]
        model = LSAModel(LSAConfig(n_components=3))
        model.fit(TOY_CORPUS)
        vectors = model.transform(docs)
        self.assertEqual(vectors.shape, (5, 3))
        self.assertFalse(np.isnan(vectors).any())
        self.assertFalse(np.isinf(vectors).any())
        self.assertTrue(np.allclose(vectors[1], 0.0))
        self.assertTrue(np.allclose(vectors[3], 0.0))

    def test_too_small_corpus(self):
        """A 1-document corpus clamps to 1 dimension instead of crashing."""
        model = LSAModel(LSAConfig(n_components=300))
        info = model.fit(["only one document here"])
        self.assertEqual(info["actual_dimensions"], 1)
        vectors = model.transform(["only one document here"])
        self.assertEqual(vectors.shape, (1, 1))

    def test_all_empty_corpus_raises(self):
        model = LSAModel(LSAConfig())
        with self.assertRaises(ValueError):
            model.fit(["", "  ", "..."])


if __name__ == "__main__":
    unittest.main()
