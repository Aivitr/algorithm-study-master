"""
service 层端到端测试（负责人：葛艾蓝）。

用假数据走一遍 analyze_group 的完整流程：
注册 → 分析 → 检查统一结果格式。
"""

import unittest
from unittest.mock import patch

from gca_engine.schemas import AnalysisStatus, GroupAnalysisResult, Utterance
from gca_engine.service import (
    analyze_group,
    clear_meeting,
    list_meetings,
    register_meeting,
)


def _make_utterances(meeting_id="demo-1"):
    """3 名学生、6 条发言的假数据（有意义的英文短句，方便 LSA）。"""
    lines = [
        ("u001", "I think this plan works", 10.0),
        ("u002", "I agree but time is short", 40.0),
        ("u003", "We can split the work into steps", 90.0),
        ("u001", "Yes let us build the core first", 150.0),
        ("u003", "I will handle the data part", 210.0),
        ("u002", "I will write the tests", 280.0),
    ]
    return [
        Utterance(meeting_id, spk, text, ts, f"t{i}")
        for i, (spk, text, ts) in enumerate(lines)
    ]


class TestAnalyzeGroup(unittest.TestCase):

    def tearDown(self):
        for mid in list_meetings():
            clear_meeting(mid)

    def test_engine_exception_returns_internal_error(self):
        meeting_id = "engine-error"
        register_meeting(meeting_id, _make_utterances(meeting_id))

        with patch(
            "gca_engine.service.analyze_utterances",
            side_effect=RuntimeError("simulated engine failure"),
        ):
            result = analyze_group(meeting_id)

        self.assertEqual(result.status, AnalysisStatus.INTERNAL_ERROR)
        self.assertEqual(result.meeting_id, meeting_id)
        self.assertEqual(result.student_metrics, {})
        self.assertEqual(result.group_metrics, {})
        self.assertIsNotNone(result.error)
        self.assertIn("RuntimeError", result.error)
        self.assertIn("simulated engine failure", result.error)

    def test_success_full_flow(self):
        utterances = _make_utterances()
        register_meeting("demo-1", utterances)
        result = analyze_group("demo-1")

        self.assertEqual(result.meeting_id, "demo-1")
        self.assertEqual(result.status, AnalysisStatus.SUCCESS)
        self.assertIsNone(result.error)

        # 学生指标：3 名学生，每人恰好 6 个指标
        self.assertEqual(set(result.student_metrics), {"u001", "u002", "u003"})
        expected_metrics = {
            "participation", "internal_cohesion", "overall_responsivity",
            "social_impact", "newness", "communication_density",
        }
        for spk, metrics in result.student_metrics.items():
            self.assertEqual(set(metrics), expected_metrics)
            for v in metrics.values():
                self.assertIsInstance(v, float)

        # 小组指标：6 个指标，每个都有 mean/min/max/std/count
        self.assertEqual(set(result.group_metrics), expected_metrics)
        for stats in result.group_metrics.values():
            self.assertEqual(
                set(stats), {"mean", "min", "max", "std", "count"}
            )
            self.assertEqual(stats["count"], 3)

        # timeline（v0.2 已实现）：固定 5 分钟窗口 + 滑动 5 分钟窗口
        self.assertIsNotNone(result.timeline)
        self.assertIn("fixed_5min", result.timeline)
        self.assertIn("sliding_5min", result.timeline)
        # 这节假课堂只有 280 秒，固定窗口只有 1 个
        self.assertEqual(len(result.timeline["fixed_5min"]), 1)
        self.assertTrue(result.timeline["sliding_5min"])
        self.assertEqual(result.metadata["timeline"]["sliding_step_seconds"], 30)

        # 结果可以序列化成 dict
        d = result.to_dict()
        self.assertEqual(d["meeting_id"], "demo-1")

    def test_not_found(self):
        result = analyze_group("no-such-meeting")
        self.assertEqual(result.status, AnalysisStatus.NOT_FOUND)
        self.assertIsNotNone(result.error)
        self.assertEqual(result.student_metrics, {})

    def test_invalid_meeting_id(self):
        for bad in (123, "", "   "):
            result = analyze_group(bad)
            self.assertEqual(result.status, AnalysisStatus.INVALID_INPUT)

    def test_empty_transcript(self):
        register_meeting("empty-1", [])
        result = analyze_group("empty-1")
        self.assertEqual(result.status, AnalysisStatus.EMPTY_TRANSCRIPT)

    def test_single_speaker_still_computes(self):
        register_meeting("solo-1", [
            Utterance("solo-1", "u001", "I like apples", 1.0, "t1"),
            Utterance("solo-1", "u001", "I like oranges", 10.0, "t2"),
        ])
        result = analyze_group("solo-1")
        self.assertEqual(result.status, AnalysisStatus.SINGLE_SPEAKER)
        self.assertEqual(set(result.student_metrics), {"u001"})
        self.assertTrue(any("只有一名学生" in w for w in result.warnings))

    def test_insufficient_data_too_few(self):
        register_meeting("tiny-1", [
            Utterance("tiny-1", "u001", "I like apples", 1.0, "t1"),
        ])
        result = analyze_group("tiny-1")
        self.assertEqual(result.status, AnalysisStatus.INSUFFICIENT_DATA)

    def test_insufficient_data_all_empty_text(self):
        register_meeting("blank-1", [
            Utterance("blank-1", "u001", "...", 1.0, "t1"),
            Utterance("blank-1", "u002", "!!!", 10.0, "t2"),
        ])
        result = analyze_group("blank-1")
        self.assertEqual(result.status, AnalysisStatus.INSUFFICIENT_DATA)

    def test_register_meeting_validation(self):
        with self.assertRaises(ValueError):
            register_meeting("x", ["not an utterance"])
        with self.assertRaises(ValueError):
            register_meeting(123, [])

    def test_list_and_clear(self):
        register_meeting("demo-1", _make_utterances())
        self.assertIn("demo-1", list_meetings())
        clear_meeting("demo-1")
        self.assertNotIn("demo-1", list_meetings())
        clear_meeting("never-existed")  # 不存在也不报错

    def test_register_rejects_mismatched_meeting_id(self):
        with self.assertRaisesRegex(ValueError, "meeting_id"):
            register_meeting(
                "target-group",
                _make_utterances("other-group"),
            )

        self.assertNotIn("target-group", list_meetings())

    def test_register_rejects_mixed_meetings_without_overwrite(self):
        meeting_id = "target-group"
        original = _make_utterances(meeting_id)
        register_meeting(meeting_id, original)

        mixed = _make_utterances(meeting_id)
        mixed[0] = Utterance(
            meeting_id="other-group",
            speaker_id="other-student",
            text="This is another group discussion",
            timestamp=5.0,
            utterance_id="foreign-1",
        )

        with self.assertRaisesRegex(ValueError, "meeting_id"):
            register_meeting(meeting_id, mixed)

        result = analyze_group(meeting_id)
        self.assertEqual(result.status, AnalysisStatus.SUCCESS)
        self.assertEqual(
            set(result.student_metrics),
            {u.speaker_id for u in original},
        )


    def test_registration_isolated_from_caller_mutations(self):
        meeting_id = "snapshot-group"
        original = _make_utterances(meeting_id)
        register_meeting(meeting_id, original)

        original[0].meeting_id = "other-group"
        original[0].speaker_id = "foreign-student"
        original[0].timestamp = float("nan")
        original.clear()

        result = analyze_group(meeting_id)
        self.assertEqual(result.status, AnalysisStatus.SUCCESS)
        self.assertEqual(result.metadata["n_utterances"], 6)
        self.assertEqual(set(result.student_metrics), {"u001", "u002", "u003"})

    def test_invalid_mutated_record_does_not_overwrite_registration(self):
        meeting_id = "snapshot-group"
        register_meeting(meeting_id, _make_utterances(meeting_id))
        invalid = _make_utterances(meeting_id)
        invalid[0].timestamp = float("nan")

        with self.assertRaisesRegex(ValueError, "timestamp"):
            register_meeting(meeting_id, invalid)

        self.assertEqual(analyze_group(meeting_id).status, AnalysisStatus.SUCCESS)

    def test_engine_mutation_does_not_damage_registration(self):
        meeting_id = "snapshot-group"
        register_meeting(meeting_id, _make_utterances(meeting_id))

        def broken_engine(mid, utterances):
            utterances[0].speaker_id = "foreign-student"
            utterances.clear()
            raise RuntimeError("engine modified its input")

        with patch("gca_engine.service.analyze_utterances", side_effect=broken_engine):
            self.assertEqual(analyze_group(meeting_id).status, AnalysisStatus.INTERNAL_ERROR)

        result = analyze_group(meeting_id)
        self.assertEqual(result.status, AnalysisStatus.SUCCESS)
        self.assertEqual(result.metadata["n_utterances"], 6)
        self.assertNotIn("foreign-student", result.student_metrics)

    def test_fixed_only_timeline_and_window_errors_are_preserved(self):
        meeting_id = "fixed-group"
        register_meeting(meeting_id, _make_utterances(meeting_id))
        expected = GroupAnalysisResult(
            meeting_id=meeting_id,
            status=AnalysisStatus.SUCCESS,
            student_metrics={},
            group_metrics={},
            timeline={"fixed_5min": [
                {"start_second": 0, "end_second": 300, "group_metrics": {}},
            ]},
            metadata={
                "timeline": {"fixed_window_seconds": 300, "n_fixed_windows": 1},
                "window_errors": [{
                    "kind": "fixed", "start_second": 0, "end_second": 300,
                    "error": "RuntimeError: simulated window failure",
                }],
            },
            warnings=["有 1 个时间窗口计算失败"],
        )
        with patch("gca_engine.service.analyze_utterances", return_value=expected):
            actual = analyze_group(meeting_id)

        self.assertEqual(actual.to_dict(), expected.to_dict())
        self.assertNotIn("sliding_5min", actual.timeline)

    def test_unavailable_timeline_is_preserved(self):
        meeting_id = "no-timeline-group"
        register_meeting(meeting_id, _make_utterances(meeting_id))
        expected = GroupAnalysisResult(
            meeting_id=meeting_id, status=AnalysisStatus.SUCCESS,
            student_metrics={}, group_metrics={}, timeline=None,
        )
        with patch("gca_engine.service.analyze_utterances", return_value=expected):
            self.assertIsNone(analyze_group(meeting_id).timeline)


if __name__ == "__main__":
    unittest.main()
