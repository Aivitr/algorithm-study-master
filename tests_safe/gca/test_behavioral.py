"""行为投入维度测试。

覆盖：正常计数与参与比例、空数据、单条发言、空文本过滤、
单人发言、GCA 互动指标复用、时间窗口与非法输入。
"""

import json
import unittest

from gca_engine.engagement.behavioral import analyze_behavioral
from gca_engine.schemas import AnalysisStatus, GroupAnalysisResult, Utterance


def _utterance(speaker, timestamp, text="发言内容", uid=None, end_time=None):
    return Utterance(
        meeting_id="m1",
        speaker_id=speaker,
        text=text,
        timestamp=float(timestamp),
        utterance_id=uid or f"{speaker}-{timestamp}",
        end_time=end_time,
    )


class TestAnalyzeBehavioral(unittest.TestCase):
    def test_two_speakers_counts_and_participation(self):
        result = analyze_behavioral(
            "m1",
            [
                _utterance("u1", 10),
                _utterance("u1", 70),
                _utterance("u1", 130),
                _utterance("u2", 40),
            ],
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.student_metrics["u1"]["utterance_count"], 3.0)
        self.assertAlmostEqual(result.student_metrics["u1"]["participation"], 0.75)
        self.assertAlmostEqual(result.student_metrics["u2"]["participation"], 0.25)
        self.assertEqual(result.group_metrics["utterance_count"]["count"], 2)
        self.assertAlmostEqual(result.group_metrics["utterance_count"]["mean"], 2.0)
        self.assertEqual(result.metadata["n_speakers"], 2)
        self.assertFalse(result.metadata["action_data_available"])

    def test_frequency_uses_observed_duration(self):
        result = analyze_behavioral(
            "m1",
            [
                _utterance("u1", 0, end_time=0),
                _utterance("u1", 120, end_time=120),
            ],
        )
        self.assertAlmostEqual(result.student_metrics["u1"]["utterances_per_minute"], 1.0)

    def test_empty_utterances_are_unavailable(self):
        result = analyze_behavioral("m1", [_utterance("u1", 10, text="   ")])

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.student_metrics, {})
        self.assertEqual(result.error, "没有任何发言记录")
        self.assertEqual(result.metadata["n_excluded_empty"], 1)

    def test_single_utterance_is_insufficient_with_counts(self):
        result = analyze_behavioral("m1", [_utterance("u1", 10)])

        self.assertEqual(result.status, "insufficient")
        self.assertEqual(result.student_metrics["u1"]["utterance_count"], 1.0)
        self.assertIsNotNone(result.error)

    def test_single_speaker_is_ok_with_warning(self):
        result = analyze_behavioral("m1", [_utterance("u1", 10), _utterance("u1", 20)])

        self.assertEqual(result.status, "ok")
        self.assertTrue(any("仅有一名学生" in item for item in result.warnings))

    def test_gca_interaction_metrics_are_reused(self):
        gca = GroupAnalysisResult(
            meeting_id="m1",
            status=AnalysisStatus.SUCCESS.value,
            student_metrics={
                "u1": {"social_impact": 0.4, "communication_density": 0.7},
                "u2": {"social_impact": 0.2, "communication_density": 0.3},
            },
            group_metrics={},
        )
        result = analyze_behavioral(
            "m1",
            [_utterance("u1", 10), _utterance("u2", 20)],
            gca_result=gca,
        )

        self.assertAlmostEqual(result.student_metrics["u1"]["gca_social_impact"], 0.4)
        self.assertAlmostEqual(result.student_metrics["u2"]["gca_communication_density"], 0.3)
        self.assertEqual(result.metadata["gca_interaction_students"], 2)

    def test_unusable_gca_does_not_reuse_metrics(self):
        gca = GroupAnalysisResult(
            meeting_id="m1",
            status=AnalysisStatus.INTERNAL_ERROR.value,
            student_metrics={"u1": {"social_impact": 0.4}},
            group_metrics={},
        )
        result = analyze_behavioral(
            "m1", [_utterance("u1", 10), _utterance("u1", 20)], gca_result=gca
        )

        self.assertNotIn("gca_social_impact", result.student_metrics["u1"])
        self.assertTrue(any("GCA 分析未完整完成" in item for item in result.warnings))

    def test_timeline_has_fixed_and_sliding_windows(self):
        result = analyze_behavioral(
            "m1",
            [
                _utterance("u1", 10),
                _utterance("u2", 70),
                _utterance("u1", 610),
            ],
        )

        self.assertIsNotNone(result.timeline)
        self.assertEqual(len(result.timeline["fixed_5min"]), 3)
        self.assertEqual(result.timeline["fixed_5min"][0]["start_second"], 0)
        self.assertEqual(
            result.timeline["fixed_5min"][0]["group_metrics"]["utterance_count"]["count"], 2
        )
        self.assertTrue(result.timeline["sliding_5min"])

    def test_end_time_extends_duration(self):
        result = analyze_behavioral(
            "m1",
            [
                _utterance("u1", 0, end_time=600),
                _utterance("u2", 10, end_time=10),
            ],
        )
        self.assertEqual(result.metadata["duration_seconds"], 600.0)

    def test_meeting_mismatch_raises(self):
        other = Utterance(
            meeting_id="m2",
            speaker_id="u1",
            text="x",
            timestamp=1.0,
            utterance_id="1",
        )
        with self.assertRaises(ValueError):
            analyze_behavioral("m1", [other])

    def test_result_is_json_serializable(self):
        result = analyze_behavioral("m1", [_utterance("u1", 10), _utterance("u2", 20)])
        json.dumps(result.to_dict(), allow_nan=False)


if __name__ == "__main__":
    unittest.main()
