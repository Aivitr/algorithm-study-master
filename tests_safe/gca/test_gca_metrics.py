"""
GCA 六指标核心测试 —— 从 ami_parser 迁移（负责人：陈虹宇）。

Tests A-I use small toy meetings whose expected values are computed by
hand from the paper's definitions (Dowell, Nixon & Graesser).  All
tests run on synthetic data only — no AMI corpus access.
"""

import unittest

import numpy as np

from gca_engine.core.communication_density import (
    contribution_density,
    participant_density,
)
from gca_engine.core.config import GCAConfig
from gca_engine.core.metrics import compute_gca_metrics
from gca_engine.core.newness import contribution_newness, participant_newness
from gca_engine.core.participation import participation, participation_series
from gca_engine.core.responsivity import (
    internal_cohesion,
    lagged_responsivity,
    overall_responsivity,
    social_impact,
    spanning_responsivity,
)
from gca_engine.core.similarity import cosine


def assert_all_finite(value):
    """Recursively assert a GCAResult.to_dict() contains no NaN / Inf."""
    if isinstance(value, dict):
        for v in value.values():
            assert_all_finite(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            assert_all_finite(v)
    elif isinstance(value, (int, float)):
        assert np.isfinite(value), f"non-finite value: {value!r}"
    elif isinstance(value, str):
        pass
    else:
        raise TypeError(f"unexpected type {type(value)}: {value!r}")


class TestGCA(unittest.TestCase):
    """Tests A-I of the Phase 5A specification."""

    def test_A_participation(self):
        # A B A C  ->  A = 2/4, B = 1/4, C = 1/4
        speakers = ["A", "B", "A", "C"]
        part = participation(speakers)
        self.assertEqual(part, {"A": 0.5, "B": 0.25, "C": 0.25})
        order, series = participation_series(speakers)
        self.assertEqual(order, ["A", "B", "C"])
        self.assertTrue(np.array_equal(series["A"], [True, False, True, False]))
        self.assertTrue(np.array_equal(series["B"], [False, True, False, False]))
        self.assertTrue(np.array_equal(series["C"], [False, False, False, True]))
        # every contribution belongs to exactly one speaker
        stack = np.vstack([series[s] for s in order])
        self.assertTrue(np.array_equal(stack.sum(axis=0), np.ones(4, dtype=int)))

    def test_B_responsivity_orientation(self):
        # A speaks, then B repeats A's vector, then C speaks something
        # orthogonal to B: only the pair (B responds to A) is similar.
        speakers = ["A", "B", "C"]
        vectors = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
        order, r1, n_zero = lagged_responsivity(speakers, vectors, 1)
        self.assertEqual(order, ["A", "B", "C"])
        self.assertAlmostEqual(r1[order.index("B"), order.index("A")], 1.0)
        self.assertAlmostEqual(r1[order.index("A"), order.index("B")], 0.0)
        self.assertAlmostEqual(r1[order.index("C"), order.index("B")], 0.0)
        self.assertEqual(n_zero, 0)

    def test_C_internal_cohesion(self):
        # A_1 ~ A_2 (identical vectors) but A_1 _|_ B_2: only the
        # diagonal entry R[A, A] is high.
        speakers = ["A", "A", "B"]
        vectors = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
        order, _, r_bar, _ = spanning_responsivity(speakers, vectors, 1)
        cohesion = internal_cohesion(r_bar, speakers)
        self.assertAlmostEqual(cohesion["A"], 1.0)
        self.assertAlmostEqual(cohesion["B"], 0.0)
        self.assertAlmostEqual(r_bar[order.index("B"), order.index("A")], 0.0)

    def test_D_overall_responsivity_row_mean(self):
        # Worked-example matrix (rows/cols A B C):
        # R_bar = [[1,0,0],[1,0,0],[0,0,0]]
        # Row means without diagonal: A=0, B=(1+0)/2=0.5, C=0.
        r_bar = np.array([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
        speakers = ["A", "B", "C"]
        or_metric = overall_responsivity(r_bar, speakers)
        self.assertAlmostEqual(or_metric["A"], 0.0)
        self.assertAlmostEqual(or_metric["B"], 0.5)
        self.assertAlmostEqual(or_metric["C"], 0.0)

    def test_E_social_impact_column_mean(self):
        # Same matrix: column means without diagonal: A=(1+0)/2=0.5,
        # B=0, C=0.
        r_bar = np.array([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
        speakers = ["A", "B", "C"]
        si = social_impact(r_bar, speakers)
        self.assertAlmostEqual(si["A"], 0.5)
        self.assertAlmostEqual(si["B"], 0.0)
        self.assertAlmostEqual(si["C"], 0.0)

    def test_F_newness(self):
        # d1 = [1,0,0], d2 = [1,0,0], d3 = [0,1,0]:
        # t1 -> 1.0 (deterministic), d2 -> 0.0 (inside subspace),
        # d3 -> 1.0 (orthogonal to subspace).
        vectors = np.array([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        newness = contribution_newness(vectors)
        np.testing.assert_allclose(newness, [1.0, 0.0, 1.0], atol=1e-12)
        # Exact paper formula ||n|| / (||n|| + ||g||): for d = [1,1,0]
        # after history {[1,0,0]}: g = [1,0,0] (norm 1), n = [0,1,0]
        # (norm 1) -> 1 / (1 + 1) = 0.5 (not the sine 1/sqrt(2)).
        vectors2 = np.array([[1.0, 0.0, 0.0], [1.0, 1.0, 0.0]])
        newness2 = contribution_newness(vectors2)
        np.testing.assert_allclose(newness2, [1.0, 0.5], atol=1e-12)
        # participant-level means
        by_speaker = participant_newness(
            np.array([1.0, 0.0, 0.0, 1.0, 0.0]), ["A", "A", "B", "A", "C"]
        )
        self.assertAlmostEqual(by_speaker["A"], 2.0 / 3.0)
        self.assertAlmostEqual(by_speaker["B"], 0.0)
        self.assertAlmostEqual(by_speaker["C"], 0.0)

    def test_G_density_totals_not_mean(self):
        # Speaker A (indices 0, 1, 3): norms 1, 1, 1 with word counts
        # 1, 1, 2.  Total/total = 3 / 4 = 0.75; mean of per-utterance
        # densities = (1 + 1 + 0.5) / 3 = 5/6 — the two must differ.
        vectors = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 0.0]])
        word_counts = [1.0, 1.0, 4.0, 2.0]
        speakers = ["A", "A", "B", "A"]
        d_t = contribution_density(vectors, word_counts)
        np.testing.assert_allclose(d_t, [1.0, 1.0, 0.25, 0.5], atol=1e-12)
        d_by_spk = participant_density(vectors, word_counts, speakers)
        self.assertAlmostEqual(d_by_spk["A"], 0.75)
        self.assertAlmostEqual(d_by_spk["B"], 0.25)
        per_utt_mean = float(np.mean(d_t[np.array([s == "A" for s in speakers])]))
        self.assertAlmostEqual(per_utt_mean, 5.0 / 6.0)
        self.assertNotAlmostEqual(d_by_spk["A"], per_utt_mean)

    def test_H_three_four_five_speakers(self):
        for k, n in ((3, 5), (4, 6), (5, 7)):
            speakers = [chr(ord("A") + t % k) for t in range(n)]
            vectors = np.arange(n * 2, dtype=float).reshape(n, 2) + 1.0
            word_counts = [float(1 + (t % 3)) for t in range(n)]
            result = compute_gca_metrics(
                f"M{k}", speakers, vectors, word_counts,
                GCAConfig(spanning_window=2),
            )
            self.assertEqual(result.speakers, sorted(set(speakers)))
            self.assertEqual(len(result.speakers), k)
            self.assertEqual(result.n_utterances, n)
            self.assertAlmostEqual(sum(result.participation.values()), 1.0)
            for name in ("internal_cohesion", "overall_responsivity",
                         "social_impact", "newness_by_speaker",
                         "density_by_speaker"):
                self.assertEqual(set(getattr(result, name)), set(result.speakers))
            assert_all_finite(result.to_dict())

    def test_I_zero_vectors_and_zero_words(self):
        speakers = ["A", "B"]
        vectors = np.array([[0.0, 0.0], [1.0, 0.0]])
        word_counts = [0.0, 2.0]
        result = compute_gca_metrics(
            "Z", speakers, vectors, word_counts, GCAConfig(spanning_window=1)
        )
        # newness: zero first contribution -> 0.0 (policy); the second
        # one has an empty (zero-excluded) history -> 1.0.
        np.testing.assert_allclose(result.newness, [0.0, 1.0], atol=1e-12)
        # density: 0 words -> 0.0; 1 / 2 = 0.5.
        np.testing.assert_allclose(result.density, [0.0, 0.5], atol=1e-12)
        # responsivity: the only pair (B responds to A) has an undefined
        # cosine -> 0.0 by policy, and the pair is recorded.
        rb = np.array(result.responsivity_matrix)
        self.assertAlmostEqual(
            rb[result.speakers.index("B"), result.speakers.index("A")], 0.0
        )
        self.assertEqual(result.zero_vector["n_zero_vectors"], 1)
        self.assertEqual(result.zero_vector["zero_vector_indices"], [0])
        self.assertEqual(result.zero_vector["n_zero_word_counts"], 1)
        self.assertEqual(result.zero_vector["zero_word_count_indices"], [0])
        self.assertEqual(result.zero_vector["n_zero_vector_similarity_pairs"], 1)
        assert_all_finite(result.to_dict())
        # cosine itself resolves zero vectors to 0.0 without NaN
        self.assertAlmostEqual(cosine([0.0, 0.0], [1.0, 0.0]), 0.0)
        self.assertAlmostEqual(cosine([1.0, 0.0], [1.0, 0.0]), 1.0)
        self.assertAlmostEqual(cosine([1.0, 0.0], [0.0, 1.0]), 0.0)

    def test_spanning_averages_all_lags(self):
        # n = 3, window = 5: lags 3..5 have no pairs and contribute zero
        # matrices to the (1/w) average.  R_1[B,A] = 1, all else 0
        # (R_2[C,A] has cosine 0), so R_bar[B,A] = 1/5.
        speakers = ["A", "B", "C"]
        vectors = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
        order, lags, r_bar, _ = spanning_responsivity(speakers, vectors, 5)
        self.assertEqual(len(lags), 5)
        self.assertAlmostEqual(r_bar[order.index("B"), order.index("A")], 0.2)
        self.assertAlmostEqual(r_bar[order.index("C"), order.index("B")], 0.0)
        self.assertAlmostEqual(r_bar[order.index("C"), order.index("A")], 0.0)
        self.assertAlmostEqual(r_bar.sum(), 0.2)

    def test_custom_window_20(self):
        # n = 3, custom w = 20 (the calibrated default): lags 3..20
        # have no pairs and contribute zero matrices, so
        # R_bar[B,A] = 1/20 and every matrix past lag 2 is all-zero.
        speakers = ["A", "B", "C"]
        vectors = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
        order, lags, r_bar, _ = spanning_responsivity(speakers, vectors, 20)
        self.assertEqual(len(lags), 20)
        self.assertAlmostEqual(r_bar[order.index("B"), order.index("A")], 0.05)
        for m in lags[2:]:
            self.assertTrue(np.array_equal(m, np.zeros((3, 3))))
        assert_all_finite(r_bar.tolist())

    def test_single_speaker(self):
        # k = 1: OR and SI have no off-diagonal participants -> 0.0;
        # internal cohesion = R[A,A] = cosine 1.
        result = compute_gca_metrics(
            "S", ["A", "A"], np.array([[1.0, 0.0], [1.0, 0.0]]), [1.0, 1.0],
            GCAConfig(spanning_window=1),
        )
        self.assertAlmostEqual(result.internal_cohesion["A"], 1.0)
        self.assertAlmostEqual(result.overall_responsivity["A"], 0.0)
        self.assertAlmostEqual(result.social_impact["A"], 0.0)
        assert_all_finite(result.to_dict())

    def test_config_defaults_and_notes(self):
        # The formal default is the original GCA-calibrated w = 20.
        cfg = GCAConfig()
        self.assertEqual(cfg.spanning_window, 20)
        self.assertEqual(cfg.zero_vector_policy, "zero")
        self.assertEqual(cfg.word_count, "preprocessed_tokens")
        # Provenance notes travel with every config snapshot.
        notes = cfg.to_dict()["notes"]
        self.assertIn("spanning_window", notes)
        self.assertIn("zero_vector_policy", notes)
        self.assertIn("first_contribution_newness", notes)

    def test_config_validation(self):
        with self.assertRaises(ValueError):
            GCAConfig(spanning_window=0)
        with self.assertRaises(ValueError):
            GCAConfig(zero_vector_policy="bogus")
        with self.assertRaises(ValueError):
            GCAConfig(word_count="other")

    def test_invalid_policy_raises(self):
        with self.assertRaises(ValueError):
            contribution_newness(np.array([[1.0, 0.0]]), zero_vector_policy="bogus")

    def test_empty_meeting_raises(self):
        with self.assertRaises(ValueError):
            compute_gca_metrics("E", [], np.zeros((0, 2)), [])

    def test_length_mismatch_raises(self):
        with self.assertRaises(ValueError):
            compute_gca_metrics("L", ["A", "B"], np.zeros((3, 2)), [1.0, 1.0])
        with self.assertRaises(ValueError):
            compute_gca_metrics("L", ["A", "B"], np.zeros((2, 2)), [1.0])

    def test_deterministic(self):
        speakers = ["A", "B", "A", "C", "B"]
        vectors = np.array(
            [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 0.0]]
        )
        word_counts = [1.0, 1.0, 3.0, 4.0, 2.0]
        cfg = GCAConfig(spanning_window=2)
        r1 = compute_gca_metrics("D", speakers, vectors, word_counts, cfg)
        r2 = compute_gca_metrics("D", speakers, vectors, word_counts, cfg)
        self.assertEqual(r1.to_dict(), r2.to_dict())


if __name__ == "__main__":
    unittest.main()
