"""
三维统一整合入口测试（组长：陈虹宇）。

覆盖：
- 三维正常输入 → success，投影结构、metadata 与严格 JSON 序列化
- 单维度 unavailable（无情绪记录）→ 其余维度照常返回，投影不出现该维度键
- 无发言 / 全空文本 → insufficient_data；单人 → single_speaker
- gca_result 复用（行为维度 gca_reused）与维度 warnings 汇总
- 仅出现在情绪记录中的用户只投影情感维度键
- 非法输入抛 ValueError（整合层浅校验 + 维度模块深校验传播）
详细口径见 docs/engagement_protocol.md 第 5 节。
"""

import json
import unittest

from gca_engine.engagement import (
    analyze_engagement,
)
from gca_engine.engagement.protocols import EmotionRecord, SpeechQualityRecord
from gca_engine.engine import ENGINE_VERSION, analyze_utterances
from gca_engine.schemas import AnalysisStatus, Utterance


def _u(
    speaker_id: str,
    timestamp: float,
    text: str = "我觉得这个方案可以分两步来讨论",
    uid: str | None = None,
    meeting_id: str = "m1",
) -> Utterance:
    return Utterance(
        meeting_id=meeting_id,
        speaker_id=speaker_id,
        text=text,
        timestamp=float(timestamp),
        utterance_id=uid or f"u-{speaker_id}-{timestamp}",
    )


def _three_speaker_utterances() -> list[Utterance]:
    return [
        _u("u1", 10.0, "我们可以先比较时间复杂度和空间复杂度", uid="t1"),
        _u("u2", 40.0, "赞同，另外还要考虑数据预处理和排序成本", uid="t2"),
        _u("u3", 90.0, "如果输入已经有序，二分查找会更高效", uid="t3"),
        _u("u1", 150.0, "那我们先总结有序和无序两种场景的代价", uid="t4"),
        _u("u2", 210.0, "我来补充一个边界样例帮助验证复杂度", uid="t5"),
    ]


def _emotion_records() -> list[EmotionRecord]:
    return [
        EmotionRecord("m1", "u1", "thinking", 15.0),
        EmotionRecord("m1", "u2", "happy", 50.0),
        EmotionRecord("m1", "u1", "calm", 95.0),
    ]


def _quality_records() -> list[SpeechQualityRecord]:
    return [
        SpeechQualityRecord("t1", quality_score=82.0, feedback="观点明确"),
        SpeechQualityRecord("t2", quality_score=86.0, feedback="有效回应同伴"),
        SpeechQualityRecord("t3", quality_score=78.0, feedback="补充了边界条件"),
        SpeechQualityRecord("t4", quality_score=84.0, feedback="归纳了两类场景"),
        SpeechQualityRecord("t5", quality_score=80.0, feedback="举例验证复杂度"),
    ]


class TestEngagementIntegration(unittest.TestCase):
    def test_full_three_dimensions_success(self):
        utterances = _three_speaker_utterances()
        gca = analyze_utterances("m1", utterances)
        self.assertEqual(gca.status, AnalysisStatus.SUCCESS)

        result = analyze_engagement(
            "m1",
            utterances,
            emotion_records=_emotion_records(),
            quality_records=_quality_records(),
            gca_result=gca,
        )

        self.assertEqual(result.status, AnalysisStatus.SUCCESS.value)
        self.assertIsNone(result.error)
        self.assertEqual(list(result.dimensions), ["emotional", "behavioral", "cognitive"])
        self.assertEqual(
            result.metadata["dimension_status"],
            {"emotional": "ok", "behavioral": "ok", "cognitive": "ok"},
        )
        self.assertEqual(result.metadata["engine_version"], ENGINE_VERSION)
        self.assertEqual(result.metadata["protocol_version"], "1.0")
        self.assertEqual(result.metadata["n_utterances"], 5)
        self.assertEqual(result.metadata["n_speakers"], 3)
        self.assertIsNone(result.timeline)

        # 学生投影：有该维度数据的用户才出现对应键（u1/u2 三键齐全，
        # u3 无情绪记录，只有行为与认知键）
        for uid in ("u1", "u2"):
            self.assertEqual(
                set(result.student_metrics[uid]), {"emotional", "behavioral", "cognitive"}
            )
        self.assertEqual(set(result.student_metrics["u3"]), {"behavioral", "cognitive"})
        self.assertAlmostEqual(result.student_metrics["u1"]["behavioral"]["utterance_count"], 2.0)
        self.assertAlmostEqual(result.student_metrics["u1"]["emotional"]["record_count"], 2.0)
        self.assertAlmostEqual(
            result.student_metrics["u1"]["emotional"]["emotion_count_thinking"], 1.0
        )
        self.assertEqual(set(result.group_metrics), {"emotional", "behavioral", "cognitive"})
        self.assertIn("utterance_count", result.group_metrics["behavioral"])

        # 严格 JSON 序列化（无 NaN/Inf）
        serialized = json.dumps(result.to_dict(), allow_nan=False)
        self.assertIn('"protocol_version": "1.0"', serialized)

    def test_missing_emotion_records_others_ok(self):
        utterances = _three_speaker_utterances()
        gca = analyze_utterances("m1", utterances)

        result = analyze_engagement(
            "m1",
            utterances,
            emotion_records=None,
            quality_records=_quality_records(),
            gca_result=gca,
        )

        self.assertEqual(result.status, AnalysisStatus.SUCCESS.value)
        self.assertEqual(result.dimensions["emotional"].status, "unavailable")
        # 协议 5.2：不可用维度的键不出现（小组与学生投影一致）
        self.assertNotIn("emotional", result.group_metrics)
        for entry in result.student_metrics.values():
            self.assertNotIn("emotional", entry)
        self.assertEqual(result.metadata["dimension_status"]["emotional"], "unavailable")

    def test_emotion_only_user_projected_with_single_dimension_key(self):
        utterances = _three_speaker_utterances()
        gca = analyze_utterances("m1", utterances)

        result = analyze_engagement(
            "m1",
            utterances,
            emotion_records=[
                EmotionRecord("m1", "u9", "happy", 20.0),
                EmotionRecord("m1", "u9", "calm", 60.0),
            ],
            quality_records=_quality_records(),
            gca_result=gca,
        )

        self.assertIn("u9", result.student_metrics)
        self.assertEqual(set(result.student_metrics["u9"]), {"emotional"})
        self.assertNotIn("u9", result.dimensions["behavioral"].student_metrics)

    def test_no_utterances_insufficient_data(self):
        result = analyze_engagement("m1", [], emotion_records=[], quality_records=[])

        self.assertEqual(result.status, AnalysisStatus.INSUFFICIENT_DATA.value)
        self.assertIsNotNone(result.error)
        self.assertEqual(result.student_metrics, {})
        self.assertEqual(result.group_metrics, {})
        self.assertIsNone(result.timeline)
        for name in ("emotional", "behavioral", "cognitive"):
            self.assertEqual(result.dimensions[name].status, "unavailable")

    def test_all_empty_text_insufficient_data(self):
        utterances = [
            _u("u1", 10.0, text="   ", uid="t1"),
            _u("u2", 20.0, text="[静音] [噪音] <unk>", uid="t2"),
        ]
        result = analyze_engagement("m1", utterances)

        self.assertEqual(result.status, AnalysisStatus.INSUFFICIENT_DATA.value)
        self.assertIn("空文本", result.error)
        self.assertEqual(result.student_metrics, {})
        self.assertEqual(result.group_metrics, {})

    def test_single_speaker_status_and_warning(self):
        utterances = [
            _u("u1", 10.0, "我先梳理题目要求和输入限制", uid="t1"),
            _u("u1", 70.0, "接着看看动态规划状态转移怎么写", uid="t2"),
        ]
        result = analyze_engagement("m1", utterances)

        self.assertEqual(result.status, AnalysisStatus.SINGLE_SPEAKER.value)
        self.assertIsNone(result.error)
        self.assertTrue(any("只有一名学生发言" in w for w in result.warnings))

    def test_gca_result_reused_by_dimensions(self):
        utterances = _three_speaker_utterances()
        gca = analyze_utterances("m1", utterances)

        result = analyze_engagement(
            "m1",
            utterances,
            emotion_records=_emotion_records(),
            quality_records=_quality_records(),
            gca_result=gca,
        )

        self.assertTrue(result.dimensions["behavioral"].metadata["gca_reused"])
        self.assertEqual(
            result.dimensions["behavioral"].metadata["participation_source"], "gca_result"
        )

    def test_dimension_warnings_aggregated(self):
        utterances = _three_speaker_utterances()
        gca = analyze_utterances("m1", utterances)

        result = analyze_engagement(
            "m1",
            utterances,
            emotion_records=_emotion_records(),
            quality_records=_quality_records(),
            gca_result=gca,
        )

        # 真实课堂适配器无 end_time：行为维度的降级 warning 应进入整合层 warnings
        self.assertTrue(any("end_time" in w for w in result.warnings))

    def test_invalid_inputs_raise(self):
        utterances = _three_speaker_utterances()
        with self.assertRaises(ValueError):
            analyze_engagement("  ", utterances)
        with self.assertRaises(ValueError):
            analyze_engagement("m1", "not-a-list")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            analyze_engagement("m1", utterances, emotion_records=["not-a-record"])  # type: ignore[list-item]
        with self.assertRaises(ValueError):
            analyze_engagement("m1", utterances, quality_records=[{"x": 1}])  # type: ignore[list-item]

    def test_cross_meeting_inputs_raise(self):
        utterances = _three_speaker_utterances()
        with self.assertRaises(ValueError):
            analyze_engagement("m1", [_u("u1", 10.0, meeting_id="m2")])
        with self.assertRaises(ValueError):
            analyze_engagement(
                "m1", utterances, emotion_records=[EmotionRecord("m2", "u1", "happy", 1.0)]
            )


if __name__ == "__main__":
    unittest.main()
