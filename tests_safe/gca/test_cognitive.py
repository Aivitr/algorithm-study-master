"""认知投入模块的输入、指标汇总和数据不足场景。"""

import json
import unittest

from gca_engine.engagement.cognitive import analyze_cognitive

from gca_engine.engagement.protocols import EngagementDimensionResult, SpeechQualityRecord
from gca_engine.schemas import AnalysisStatus, GroupAnalysisResult, Utterance


def _utterance(index, speaker="u1", text="讨论不同的解决方法", meeting_id="m1"):
    return Utterance(meeting_id, speaker, text, index, f"t{index}")


def _score(index, value, feedback="提出了与主题相关的解释"):
    return SpeechQualityRecord(f"t{index}", quality_score=value, feedback=feedback)


def _gca(meeting_id="m1"):
    return GroupAnalysisResult(
        meeting_id,
        AnalysisStatus.SUCCESS,
        {
            "u1": {"overall_responsivity": 0.25, "newness": 0.75, "internal_cohesion": 0.5},
            "u2": {"overall_responsivity": 0.75, "newness": 0.25, "internal_cohesion": 0.25},
        },
        {},
    )


class TestCognitiveBoundaries(unittest.TestCase):
    def test_all_text_removed_has_no_available_data(self):
        utterances = [_utterance(1, text="　[静音] "), _utterance(2, "u2", "\t<unk>")]
        result = analyze_cognitive("m1", utterances, [])

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.student_metrics, {})
        self.assertEqual(result.group_metrics, {})
        self.assertEqual(result.metadata["n_utterances"], 2)
        self.assertEqual(result.metadata["n_valid_utterances"], 0)
        self.assertIsNone(result.metadata["quality_coverage"])
        self.assertTrue(result.error)
        self.assertTrue(any("清洗后为空" in item for item in result.warnings))

    def test_valid_speech_without_metrics_has_only_coverage_metadata(self):
        result = analyze_cognitive("m1", [_utterance(1), _utterance(2, "u2")], [_score(1, 0, None)])

        self.assertEqual(result.status, "insufficient")
        self.assertEqual(result.student_metrics, {})
        self.assertEqual(result.group_metrics, {})
        self.assertEqual(result.metadata["n_valid_utterances"], 2)
        self.assertEqual(result.metadata["n_valid_quality_scores"], 0)
        self.assertEqual(result.metadata["quality_coverage"], 0.0)
        self.assertTrue(result.error)

    def test_empty_utterance_list_is_unavailable(self):
        result = analyze_cognitive("m1", [], [])
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.student_metrics, {})
        self.assertEqual(result.group_metrics, {})
        self.assertIsNone(result.timeline)
        self.assertTrue(result.error)

    def test_single_utterance_keeps_valid_quality(self):
        result = analyze_cognitive("m1", [_utterance(1)], [_score(1, 80)])
        self.assertEqual(result.status, "insufficient")
        self.assertEqual(
            result.student_metrics["u1"],
            {
                "quality_mean": 80,
                "quality_count": 1,
                "quality_coverage": 1.0,
            },
        )
        self.assertEqual(result.group_metrics["quality_mean"]["std"], 0.0)

    def test_empty_text_is_excluded_from_matching_and_coverage(self):
        utterances = [_utterance(1), _utterance(2, "u2", "[噪音]")]
        result = analyze_cognitive("m1", utterances, [_score(1, 80), _score(2, 100)])
        self.assertEqual(set(result.student_metrics), {"u1"})
        self.assertEqual(result.student_metrics["u1"]["quality_mean"], 80)
        self.assertEqual(result.metadata["quality_coverage"], 1.0)
        self.assertEqual(result.metadata["n_unmatched_quality_records"], 1)


class TestCognitiveMetrics(unittest.TestCase):
    def test_complete_inputs_return_student_and_group_metrics(self):
        utterances = [_utterance(1), _utterance(2, "u2"), _utterance(3), _utterance(4, "u2")]
        quality = [_score(1, 40), _score(2, 80), _score(3, 60), _score(4, 100)]
        result = analyze_cognitive("m1", utterances, quality, _gca())

        self.assertIsInstance(result, EngagementDimensionResult)
        self.assertEqual(result.dimension, "cognitive")
        self.assertEqual(result.status, "ok")
        self.assertIsNone(result.error)
        self.assertIsNone(result.timeline)
        self.assertEqual(
            result.student_metrics,
            {
                "u1": {
                    "overall_responsivity": 0.25,
                    "newness": 0.75,
                    "internal_cohesion": 0.5,
                    "quality_mean": 50,
                    "quality_count": 2,
                    "quality_coverage": 1.0,
                },
                "u2": {
                    "overall_responsivity": 0.75,
                    "newness": 0.25,
                    "internal_cohesion": 0.25,
                    "quality_mean": 90,
                    "quality_count": 2,
                    "quality_coverage": 1.0,
                },
            },
        )
        for name, expected in {
            "overall_responsivity": (0.5, 0.25, 0.75, 0.25, 2),
            "newness": (0.5, 0.25, 0.75, 0.25, 2),
            "internal_cohesion": (0.375, 0.25, 0.5, 0.125, 2),
            "quality_mean": (70, 50, 90, 20, 2),
            "quality_count": (2, 2, 2, 0.0, 2),
            "quality_coverage": (1.0, 1.0, 1.0, 0.0, 2),
        }.items():
            with self.subTest(metric=name):
                self.assertEqual(
                    result.group_metrics[name],
                    dict(zip(("mean", "min", "max", "std", "count"), expected)),
                )

    def test_result_serializes_strictly_and_inputs_remain_unchanged(self):
        utterances = [_utterance(2, "u2"), _utterance(1)]
        quality = [_score(2, 80), _score(1, 60)]
        gca = _gca()
        before = ([u.to_dict() for u in utterances], [r.to_dict() for r in quality], gca.to_dict())

        result = analyze_cognitive("m1", utterances, quality, gca)
        result.student_metrics["u1"]["newness"] = 0.0
        payload = json.loads(json.dumps(result.to_dict(), allow_nan=False))

        self.assertEqual(payload, result.to_dict())
        self.assertEqual(
            set(payload),
            {
                "dimension",
                "status",
                "student_metrics",
                "group_metrics",
                "timeline",
                "metadata",
                "warnings",
                "error",
            },
        )
        self.assertEqual(
            before,
            (
                [u.to_dict() for u in utterances],
                [r.to_dict() for r in quality],
                gca.to_dict(),
            ),
        )

    def test_group_quality_mean_weights_students_equally(self):
        utterances = [_utterance(1), _utterance(2), _utterance(3), _utterance(4, "u2")]
        result = analyze_cognitive(
            "m1", utterances, [_score(1, 40), _score(2, 60), _score(4, 80)], _gca()
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.student_metrics["u1"]["quality_coverage"], 2 / 3)
        self.assertEqual(result.student_metrics["u2"]["quality_coverage"], 1.0)
        self.assertEqual(result.metadata["quality_coverage"], 0.75)
        self.assertAlmostEqual(result.group_metrics["quality_coverage"]["mean"], 5 / 6)
        self.assertEqual(
            result.group_metrics["quality_mean"],
            {
                "mean": 65,
                "min": 50,
                "max": 80,
                "std": 15,
                "count": 2,
            },
        )

    def test_low_coverage_can_still_be_ok_with_complete_gca(self):
        utterances = [_utterance(i, "u2" if i % 2 == 0 else "u1") for i in range(1, 11)]
        result = analyze_cognitive("m1", utterances, [_score(1, 80)], _gca())
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.metadata["quality_coverage"], 0.1)
        self.assertEqual(result.student_metrics["u2"]["overall_responsivity"], 0.75)
        self.assertEqual(result.student_metrics["u2"]["quality_count"], 0)
        self.assertEqual(result.student_metrics["u2"]["quality_coverage"], 0.0)
        self.assertNotIn("quality_mean", result.student_metrics["u2"])
        self.assertEqual(result.group_metrics["quality_mean"]["count"], 1)
        self.assertTrue(any("缺少可用质量评分" in item for item in result.warnings))


class TestCognitiveQuality(unittest.TestCase):
    def test_unmatched_scores_do_not_change_mean_or_coverage(self):
        result = analyze_cognitive("m1", [_utterance(1)], [_score(9, 100), _score(1, 40)])
        self.assertEqual(result.student_metrics["u1"]["quality_mean"], 40)
        self.assertEqual(result.metadata["n_unmatched_quality_records"], 1)
        self.assertEqual(result.metadata["quality_coverage"], 1.0)

    def test_real_zero_and_default_zero_have_different_coverage(self):
        result = analyze_cognitive(
            "m1",
            [_utterance(1), _utterance(2)],
            [
                _score(1, 0, None),
                _score(2, 0, "发言与本题无关"),
            ],
        )
        self.assertEqual(result.student_metrics["u1"]["quality_mean"], 0)
        self.assertEqual(result.student_metrics["u1"]["quality_count"], 1)
        self.assertEqual(result.metadata["quality_coverage"], 0.5)

    def test_pending_and_timeout_feedback_are_excluded(self):
        for feedback in ("评估中...", "已断句，正在评分…", "评估超时"):
            with self.subTest(feedback=feedback):
                result = analyze_cognitive("m1", [_utterance(1)], [_score(1, 50, feedback)])
                self.assertNotIn("quality_mean", result.group_metrics)
                self.assertEqual(result.metadata["n_excluded_quality_records"], 1)

    def test_fifty_is_excluded_only_when_source_evidence_is_missing(self):
        utterances = [_utterance(1), _utterance(2), _utterance(3)]
        result = analyze_cognitive(
            "m1",
            utterances,
            [
                _score(1, 50, "已评估"),
                _score(2, 50, None),
                _score(3, 50, "解释了步骤，但缺少论据"),
            ],
        )
        self.assertEqual(result.student_metrics["u1"]["quality_mean"], 50)
        self.assertEqual(result.metadata["n_valid_quality_scores"], 1)
        self.assertEqual(result.metadata["n_excluded_quality_records"], 2)
        self.assertIn("可能遗漏真实评分", result.metadata["quality_validity_limitation"])

    def test_existing_short_speech_rule_score_is_retained(self):
        record = _score(1, 35, "语句较短，建议展开详细论述")
        result = analyze_cognitive("m1", [_utterance(1)], [record])
        self.assertEqual(result.student_metrics["u1"]["quality_mean"], 35)
        self.assertEqual(result.metadata["n_valid_quality_scores"], 1)

    def test_scores_outside_range_or_nonfinite_are_excluded(self):
        for value in (-1, 101, float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value):
                record = _score(1, 60)
                # 公共构造器拒绝非有限数，模拟调用前被改动的可变记录。
                record.quality_score = value
                result = analyze_cognitive("m1", [_utterance(1)], [record])
                self.assertNotIn("quality_mean", result.group_metrics)
                self.assertEqual(result.metadata["n_excluded_quality_records"], 1)
                self.assertEqual(result.metadata["quality_coverage"], 0.0)

    def test_no_valid_scores_keeps_gca_metrics(self):
        result = analyze_cognitive(
            "m1",
            [_utterance(1), _utterance(2, "u2")],
            [
                _score(1, None),
                _score(2, 50, "评估超时"),
            ],
            _gca(),
        )
        self.assertEqual(result.status, "insufficient")
        self.assertEqual(result.student_metrics["u2"]["newness"], 0.25)
        self.assertEqual(result.group_metrics["newness"]["mean"], 0.5)
        self.assertNotIn("quality_mean", result.group_metrics)
        self.assertEqual(result.metadata["n_valid_quality_scores"], 0)


class TestCognitiveGCA(unittest.TestCase):
    def test_missing_gca_leaves_quality_available(self):
        result = analyze_cognitive("m1", [_utterance(1), _utterance(2, "u2")], [_score(2, 75)])
        self.assertEqual(result.status, "insufficient")
        self.assertEqual(result.group_metrics["quality_mean"]["mean"], 75)
        self.assertEqual(result.group_metrics["quality_mean"]["count"], 1)
        self.assertNotIn("newness", result.group_metrics)

    def test_missing_gca_field_preserves_other_fields_and_uses_valid_count(self):
        gca = _gca()
        del gca.student_metrics["u2"]["newness"]
        result = analyze_cognitive("m1", [_utterance(1), _utterance(2, "u2")], [_score(2, 75)], gca)
        self.assertEqual(result.status, "insufficient")
        self.assertNotIn("newness", result.student_metrics["u2"])
        self.assertEqual(result.student_metrics["u2"]["quality_mean"], 75)
        self.assertEqual(result.student_metrics["u2"]["internal_cohesion"], 0.25)
        self.assertEqual(
            result.group_metrics["newness"],
            {
                "mean": 0.75,
                "min": 0.75,
                "max": 0.75,
                "std": 0.0,
                "count": 1,
            },
        )

    def test_nonfinite_gca_numbers_are_excluded(self):
        gca = _gca()
        gca.student_metrics["u1"]["newness"] = float("nan")
        gca.student_metrics["u2"]["internal_cohesion"] = float("inf")
        result = analyze_cognitive("m1", [_utterance(1), _utterance(2, "u2")], [_score(1, 60)], gca)
        self.assertEqual(result.status, "insufficient")
        self.assertNotIn("newness", result.student_metrics["u1"])
        self.assertNotIn("internal_cohesion", result.student_metrics["u2"])
        self.assertEqual(result.group_metrics["newness"]["mean"], 0.25)
        self.assertEqual(result.group_metrics["internal_cohesion"]["count"], 1)
        json.dumps(result.to_dict(), allow_nan=False)

    def test_single_speaker_omits_responsivity_but_keeps_other_metrics(self):
        gca = _gca()
        gca.status = AnalysisStatus.SINGLE_SPEAKER
        del gca.student_metrics["u2"]
        gca.student_metrics["u1"]["overall_responsivity"] = 0.0
        result = analyze_cognitive("m1", [_utterance(1), _utterance(2)], [_score(1, 70)], gca)
        self.assertEqual(result.status, "insufficient")
        self.assertNotIn("overall_responsivity", result.student_metrics["u1"])
        self.assertNotIn("overall_responsivity", result.group_metrics)
        self.assertEqual(result.student_metrics["u1"]["newness"], 0.75)
        self.assertEqual(result.student_metrics["u1"]["quality_mean"], 70)
        self.assertTrue(any("缺少比较对象" in item for item in result.warnings))

    def test_extra_gca_student_is_excluded_and_reported(self):
        gca = _gca()
        gca.student_metrics["extra"] = {"newness": 1.0}
        result = analyze_cognitive("m1", [_utterance(1), _utterance(2, "u2")], [_score(1, 60)], gca)
        self.assertEqual(result.status, "insufficient")
        self.assertNotIn("extra", result.student_metrics)
        self.assertEqual(result.group_metrics["newness"]["count"], 2)
        self.assertEqual(result.group_metrics["newness"]["mean"], 0.5)
        self.assertTrue(any("缺少对应有效发言" in item for item in result.warnings))

    def test_successful_gca_with_different_utterance_count_is_reported(self):
        gca = _gca()
        gca.metadata["n_utterances"] = 10
        result = analyze_cognitive("m1", [_utterance(1), _utterance(2, "u2")], [_score(1, 60)], gca)
        self.assertEqual(result.status, "insufficient")
        self.assertTrue(any("发言条数不一致" in item for item in result.warnings))
        self.assertEqual(result.student_metrics["u1"]["quality_mean"], 60)

    def test_gca_only_keeps_available_metrics(self):
        result = analyze_cognitive("m1", [], [], _gca())
        self.assertEqual(result.status, "insufficient")
        self.assertEqual(result.group_metrics["newness"]["count"], 2)
        self.assertNotIn("quality_mean", result.group_metrics)
        self.assertIsNone(result.metadata["quality_coverage"])


class TestCognitiveValidation(unittest.TestCase):
    def test_duplicate_utterance_id(self):
        with self.assertRaisesRegex(ValueError, "重复的发言 utterance_id"):
            analyze_cognitive("m1", [_utterance(1), _utterance(1, "u2")], [])

    def test_duplicate_quality_id(self):
        with self.assertRaisesRegex(ValueError, "重复的评分 utterance_id"):
            analyze_cognitive("m1", [_utterance(1)], [_score(1, 50), _score(1, 80)])

    def test_utterance_from_other_meeting(self):
        with self.assertRaisesRegex(ValueError, "发言的 meeting_id"):
            analyze_cognitive("m1", [_utterance(1, meeting_id="m2")], [])

    def test_gca_from_other_meeting(self):
        with self.assertRaisesRegex(ValueError, "GCA 结果的 meeting_id"):
            analyze_cognitive("m1", [_utterance(1)], [], _gca("m2"))

    def test_invalid_input_types(self):
        for label, args in [
            ("meeting_id", (None, [], [], None)),
            ("utterances", ("m1", (), [], None)),
            ("utterances item", ("m1", [{}], [], None)),
            ("quality", ("m1", [], (), None)),
            ("quality item", ("m1", [], [{}], None)),
            ("gca_result", ("m1", [], [], {})),
        ]:
            with self.subTest(argument=label):
                with self.assertRaises(ValueError):
                    analyze_cognitive(*args)


if __name__ == "__main__":
    unittest.main()
