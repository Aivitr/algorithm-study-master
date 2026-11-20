"""
行为投入维度模块测试（负责人：雷梦琪）。

覆盖：
- 输入校验（非法 meeting_id / utterances / gca_result / 重复 ID / 跨小组 / 窗口参数）
- 多人正常课堂：发言次数、参与占比、频率、小组统计、参与均衡度与严格 JSON 序列化
- end_time 缺失降级、部分覆盖与完整发言时长计算
- 复用既有 GCA 结果（participation / social_impact / communication_density）及异常/不匹配防护
- 空发言、全空文本、单条发言、0 秒时长、单人多条发言、短时课堂等边界场景
- 固定/滑动时间窗口边界与 windows.py 一致性
- 与情感/认知模块组合进入 EngagementResult 的协议兼容性
"""

import json
import math
import unittest
from statistics import pstdev

from gca_engine.engagement.behavioral import analyze_behavioral
from gca_engine.engagement.cognitive import analyze_cognitive
from gca_engine.engagement.emotional import analyze_emotional
from gca_engine.engagement.protocols import (
    EmotionRecord,
    EngagementResult,
    SpeechQualityRecord,
)
from gca_engine.engine import analyze_utterances
from gca_engine.schemas import AnalysisStatus, GroupAnalysisResult, Utterance
from gca_engine.windows import build_fixed_windows, build_sliding_windows


def _u(
    speaker_id: str,
    timestamp: float,
    text: str = "我觉得这个方案可以分两步来讨论",
    uid: str | None = None,
    meeting_id: str = "m1",
    end_time: float | None = None,
) -> Utterance:
    return Utterance(
        meeting_id=meeting_id,
        speaker_id=speaker_id,
        text=text,
        timestamp=float(timestamp),
        utterance_id=uid or f"u-{speaker_id}-{timestamp}",
        end_time=end_time,
    )


def _mock_gca(
    meeting_id: str = "m1",
    status: str = AnalysisStatus.SUCCESS,
    student_metrics: dict | None = None,
    n_utterances: int | None = None,
) -> GroupAnalysisResult:
    metadata = {}
    if n_utterances is not None:
        metadata["n_utterances"] = n_utterances
    return GroupAnalysisResult(
        meeting_id=meeting_id,
        status=status,
        student_metrics=student_metrics or {},
        group_metrics={},
        metadata=metadata,
    )


class TestBehavioralInputValidation(unittest.TestCase):
    def test_empty_meeting_id_raises(self):
        with self.assertRaises(ValueError):
            analyze_behavioral("  ", [])

    def test_non_list_utterances_raises(self):
        with self.assertRaises(ValueError):
            analyze_behavioral("m1", "not-a-list")  # type: ignore[arg-type]

    def test_non_utterance_element_raises(self):
        with self.assertRaises(ValueError):
            analyze_behavioral("m1", [{"speaker_id": "u1"}])  # type: ignore[list-item]

    def test_cross_meeting_utterance_raises(self):
        with self.assertRaises(ValueError):
            analyze_behavioral("m1", [_u("u1", 10.0, meeting_id="m2")])

    def test_duplicate_utterance_id_raises(self):
        with self.assertRaises(ValueError):
            analyze_behavioral(
                "m1",
                [_u("u1", 10.0, uid="dup"), _u("u2", 20.0, uid="dup")],
            )

    def test_invalid_gca_result_raises(self):
        us = [_u("u1", 10.0, uid="t1"), _u("u2", 20.0, uid="t2")]
        with self.assertRaises(ValueError):
            analyze_behavioral("m1", us, gca_result={"status": "success"})  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            analyze_behavioral("m1", us, gca_result=_mock_gca(meeting_id="other"))
        with self.assertRaises(ValueError):
            analyze_behavioral("m1", us, gca_result=_mock_gca(status="unknown_status"))

    def test_invalid_optional_params_raise(self):
        us = [_u("u1", 10.0, uid="t1"), _u("u2", 20.0, uid="t2")]
        for bad_duration in (-1.0, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                analyze_behavioral("m1", us, duration_seconds=bad_duration)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            analyze_behavioral("m1", us, fixed_window_seconds=0)
        with self.assertRaises(ValueError):
            analyze_behavioral("m1", us, sliding_window_seconds=30, sliding_step_seconds=60)


class TestBehavioralCoreMetrics(unittest.TestCase):
    def test_multi_speaker_asymmetric_metrics_and_balance(self):
        # 故意打乱输入顺序；3 名学生分别发言 6 / 3 / 1 次，总时长 600 秒（10 分钟）
        utterances = [
            _u("u1", 600.0, uid="t10"),
            _u("u2", 120.0, uid="t2"),
            _u("u1", 30.0, uid="t1"),
            _u("u3", 360.0, uid="t6"),
            _u("u1", 180.0, uid="t3"),
            _u("u2", 240.0, uid="t4"),
            _u("u1", 280.0, uid="t5"),
            _u("u2", 420.0, uid="t7"),
            _u("u1", 480.0, uid="t8"),
            _u("u1", 540.0, uid="t9"),
        ]
        result = analyze_behavioral("m1", utterances)

        self.assertEqual(result.dimension, "behavioral")
        self.assertEqual(result.status, "ok")
        self.assertIsNone(result.error)

        # 学生级指标独立推导校验
        self.assertEqual(result.student_metrics["u1"]["utterance_count"], 6.0)
        self.assertEqual(result.student_metrics["u2"]["utterance_count"], 3.0)
        self.assertEqual(result.student_metrics["u3"]["utterance_count"], 1.0)
        self.assertAlmostEqual(result.student_metrics["u1"]["participation"], 0.6)
        self.assertAlmostEqual(result.student_metrics["u2"]["participation"], 0.3)
        self.assertAlmostEqual(result.student_metrics["u3"]["participation"], 0.1)
        self.assertAlmostEqual(result.student_metrics["u1"]["utterances_per_minute"], 0.6)
        self.assertAlmostEqual(result.student_metrics["u2"]["utterances_per_minute"], 0.3)
        self.assertAlmostEqual(result.student_metrics["u3"]["utterances_per_minute"], 0.1)
        # 真实课堂默认无 end_time：发言时长降级跳过
        for uid in ("u1", "u2", "u3"):
            self.assertNotIn("speaking_duration_seconds", result.student_metrics[uid])

        # 小组统计口径（mean/min/max/std/count，ddof=0）
        uc_stats = result.group_metrics["utterance_count"]
        self.assertAlmostEqual(uc_stats["mean"], 10.0 / 3.0)
        self.assertEqual(uc_stats["min"], 1.0)
        self.assertEqual(uc_stats["max"], 6.0)
        self.assertAlmostEqual(uc_stats["std"], pstdev([6.0, 3.0, 1.0]))
        self.assertEqual(uc_stats["count"], 3)

        p_stats = result.group_metrics["participation"]
        self.assertAlmostEqual(p_stats["mean"], 1.0 / 3.0)
        self.assertAlmostEqual(p_stats["std"], pstdev([0.6, 0.3, 0.1]))
        self.assertEqual(p_stats["count"], 3)

        # 群体分布指标与归一化香农熵
        dist = result.metadata["group_distribution"]
        expected_entropy = -(0.6 * math.log(0.6) + 0.3 * math.log(0.3) + 0.1 * math.log(0.1)) / (
            math.log(3)
        )
        self.assertEqual(dist["active_speaker_count"], 3)
        self.assertEqual(dist["total_utterances"], 10)
        self.assertAlmostEqual(dist["participation_std"], pstdev([0.6, 0.3, 0.1]))
        self.assertAlmostEqual(dist["max_participation_share"], 0.6)
        self.assertAlmostEqual(dist["normalized_entropy"], expected_entropy)

        # 无综合分、严格可 JSON 序列化
        self.assertFalse(result.metadata["composite_score_calculated"])
        self.assertFalse(result.metadata["speaking_duration_available"])
        self.assertTrue(any("end_time" in w for w in result.warnings))
        serialized = json.dumps(result.to_dict(), allow_nan=False)
        self.assertIn('"dimension": "behavioral"', serialized)

    def test_balanced_vs_imbalanced_entropy(self):
        balanced = analyze_behavioral(
            "m1",
            [
                _u("u1", 10.0, uid="t1"),
                _u("u2", 20.0, uid="t2"),
                _u("u1", 30.0, uid="t3"),
                _u("u2", 40.0, uid="t4"),
            ],
        )
        imbalanced = analyze_behavioral(
            "m1",
            [_u("u1", float(i * 10), uid=f"t{i}") for i in range(1, 10)]
            + [_u("u2", 100.0, uid="t10")],
        )
        self.assertAlmostEqual(balanced.metadata["group_distribution"]["normalized_entropy"], 1.0)
        self.assertAlmostEqual(balanced.metadata["group_distribution"]["participation_std"], 0.0)
        self.assertLess(imbalanced.metadata["group_distribution"]["normalized_entropy"], 0.5)
        self.assertAlmostEqual(imbalanced.metadata["group_distribution"]["participation_std"], 0.4)

    def test_end_time_full_partial_and_zero_duration(self):
        # 完整 end_time
        full = analyze_behavioral(
            "m1",
            [
                _u("u1", 10.0, uid="t1", end_time=18.5),
                _u("u2", 30.0, uid="t2", end_time=35.0),
                _u("u1", 50.0, uid="t3", end_time=60.0),
            ],
        )
        self.assertTrue(full.metadata["speaking_duration_available"])
        self.assertAlmostEqual(full.metadata["end_time_coverage"], 1.0)
        self.assertAlmostEqual(full.student_metrics["u1"]["speaking_duration_seconds"], 18.5)
        self.assertAlmostEqual(full.student_metrics["u2"]["speaking_duration_seconds"], 5.0)
        self.assertEqual(full.group_metrics["speaking_duration_seconds"]["count"], 2)

        # 部分 end_time：缺少 end_time 的学生不补 0
        partial = analyze_behavioral(
            "m1",
            [
                _u("u1", 10.0, uid="t1", end_time=15.0),
                _u("u2", 30.0, uid="t2", end_time=None),
                _u("u1", 60.0, uid="t3", end_time=None),
            ],
        )
        self.assertTrue(partial.metadata["speaking_duration_available"])
        self.assertAlmostEqual(partial.metadata["end_time_coverage"], 1.0 / 3.0)
        self.assertAlmostEqual(partial.student_metrics["u1"]["speaking_duration_seconds"], 5.0)
        self.assertNotIn("speaking_duration_seconds", partial.student_metrics["u2"])
        self.assertEqual(partial.group_metrics["speaking_duration_seconds"]["count"], 1)
        self.assertTrue(any("部分覆盖" in w for w in partial.warnings))

        # end_time == timestamp（0 秒有效值）
        zero_dur = analyze_behavioral(
            "m1",
            [
                _u("u1", 10.0, uid="t1", end_time=10.0),
                _u("u2", 60.0, uid="t2", end_time=60.0),
            ],
        )
        self.assertTrue(zero_dur.metadata["speaking_duration_available"])
        self.assertAlmostEqual(zero_dur.student_metrics["u1"]["speaking_duration_seconds"], 0.0)


class TestBehavioralGCAReuse(unittest.TestCase):
    def test_reuses_real_gca_result_without_recomputation(self):
        utterances = [
            _u("u1", 10.0, "我们可以先比较时间复杂度和空间复杂度", uid="t1"),
            _u("u2", 40.0, "赞同，另外还要考虑数据预处理和排序成本", uid="t2"),
            _u("u3", 90.0, "如果输入已经有序，二分查找会更高效", uid="t3"),
            _u("u1", 150.0, "那我们先总结有序和无序两种场景的代价", uid="t4"),
            _u("u2", 210.0, "我来补充一个边界样例帮助验证复杂度", uid="t5"),
        ]
        gca = analyze_utterances("m1", utterances)
        self.assertEqual(gca.status, AnalysisStatus.SUCCESS)

        result = analyze_behavioral("m1", utterances, gca_result=gca)
        self.assertEqual(result.status, "ok")
        self.assertTrue(result.metadata["gca_reused"])
        self.assertEqual(result.metadata["participation_source"], "gca_result")
        self.assertEqual(
            set(result.metadata["gca_reused_metrics"]),
            {"participation", "social_impact", "communication_density"},
        )
        for uid in ("u1", "u2", "u3"):
            self.assertAlmostEqual(
                result.student_metrics[uid]["participation"],
                gca.student_metrics[uid]["participation"],
            )
            self.assertAlmostEqual(
                result.student_metrics[uid]["social_impact"],
                gca.student_metrics[uid]["social_impact"],
            )
            self.assertAlmostEqual(
                result.student_metrics[uid]["communication_density"],
                gca.student_metrics[uid]["communication_density"],
            )
        json.dumps(result.to_dict(), allow_nan=False)

    def test_empty_utterances_fallback_participation_to_valid_utterances(self):
        utterances = [
            _u("u1", 10.0, "先看算法核心思路", uid="t1"),
            _u("u2", 40.0, "   ", uid="t2"),  # 清洗后为空
            _u("u2", 80.0, "再分析数据结构开销", uid="t3"),
        ]
        gca = _mock_gca(
            "m1",
            student_metrics={
                "u1": {
                    "participation": 1.0 / 3.0,
                    "social_impact": 0.25,
                    "communication_density": 0.4,
                },
                "u2": {
                    "participation": 2.0 / 3.0,
                    "social_impact": 0.35,
                    "communication_density": 0.5,
                },
            },
            n_utterances=3,
        )
        result = analyze_behavioral("m1", utterances, gca_result=gca)
        self.assertEqual(result.metadata["empty_text_count"], 1)
        self.assertEqual(result.metadata["participation_source"], "utterances")
        # 两条有效发言 u1/u2 各 1 条，参与占比应各为 0.5
        self.assertAlmostEqual(result.student_metrics["u1"]["participation"], 0.5)
        self.assertAlmostEqual(result.student_metrics["u2"]["participation"], 0.5)
        # 其余 GCA 指标仍可复用
        self.assertAlmostEqual(result.student_metrics["u1"]["social_impact"], 0.25)

    def test_mismatched_and_failed_gca_ignored_safely(self):
        us = [_u("u1", 10.0, uid="t1"), _u("u2", 60.0, uid="t2")]

        extra_speaker_gca = _mock_gca(
            "m1",
            student_metrics={
                "u1": {"participation": 0.4, "social_impact": 0.9},
                "u2": {"participation": 0.4, "social_impact": 0.8},
                "u999": {"participation": 0.2, "social_impact": 0.7},
            },
            n_utterances=2,
        )
        r_extra = analyze_behavioral("m1", us, gca_result=extra_speaker_gca)
        self.assertTrue(r_extra.metadata["gca_mismatch"])
        self.assertFalse(r_extra.metadata["gca_reused"])
        self.assertNotIn("social_impact", r_extra.student_metrics["u1"])
        self.assertAlmostEqual(r_extra.student_metrics["u1"]["participation"], 0.5)

        missing_speaker_gca = _mock_gca(
            "m1",
            student_metrics={"u1": {"participation": 1.0, "social_impact": 0.9}},
            n_utterances=2,
        )
        r_missing = analyze_behavioral("m1", us, gca_result=missing_speaker_gca)
        self.assertTrue(r_missing.metadata["gca_mismatch"])
        self.assertFalse(r_missing.metadata["gca_reused"])
        self.assertNotIn("social_impact", r_missing.student_metrics["u1"])

        count_mismatch_gca = _mock_gca(
            "m1",
            student_metrics={
                "u1": {"participation": 0.8, "social_impact": 0.5},
                "u2": {"participation": 0.2, "social_impact": 0.5},
            },
            n_utterances=10,
        )
        r_count = analyze_behavioral("m1", us, gca_result=count_mismatch_gca)
        self.assertTrue(r_count.metadata["gca_mismatch"])
        self.assertFalse(r_count.metadata["gca_reused"])

        failed_gca = _mock_gca("m1", status=AnalysisStatus.INSUFFICIENT_DATA)
        r_failed = analyze_behavioral("m1", us, gca_result=failed_gca)
        self.assertFalse(r_failed.metadata["gca_reused"])
        self.assertEqual(r_failed.status, "ok")

        nan_gca = _mock_gca(
            "m1",
            student_metrics={
                "u1": {
                    "participation": 0.5,
                    "social_impact": float("nan"),
                    "communication_density": float("inf"),
                },
                "u2": {
                    "participation": 0.5,
                    "social_impact": 0.3,
                    "communication_density": 0.6,
                },
            },
            n_utterances=2,
        )
        r_nan = analyze_behavioral("m1", us, gca_result=nan_gca)
        self.assertNotIn("social_impact", r_nan.student_metrics["u1"])
        self.assertNotIn("communication_density", r_nan.student_metrics["u1"])
        self.assertAlmostEqual(r_nan.student_metrics["u2"]["social_impact"], 0.3)
        json.dumps(r_nan.to_dict(), allow_nan=False)


class TestBehavioralEdgeCases(unittest.TestCase):
    def test_empty_utterances_unavailable(self):
        result = analyze_behavioral("m1", [])
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.student_metrics, {})
        self.assertEqual(result.group_metrics, {})
        self.assertIsNone(result.timeline)
        self.assertIsNotNone(result.error)

    def test_all_empty_text_unavailable(self):
        result = analyze_behavioral(
            "m1",
            [
                _u("u1", 10.0, text="   ", uid="t1"),
                _u("u2", 20.0, text="[静音] [噪音] <unk>", uid="t2"),
            ],
        )
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.student_metrics, {})
        self.assertEqual(result.group_metrics, {})
        self.assertIsNone(result.timeline)
        self.assertEqual(result.metadata["empty_text_count"], 2)

    def test_single_utterance_at_zero_insufficient_no_div_by_zero(self):
        result = analyze_behavioral("m1", [_u("u1", 0.0, uid="t1")])
        self.assertEqual(result.status, "insufficient")
        self.assertIsNotNone(result.error)
        self.assertEqual(result.student_metrics["u1"]["utterance_count"], 1.0)
        self.assertEqual(result.student_metrics["u1"]["participation"], 1.0)
        self.assertNotIn("utterances_per_minute", result.student_metrics["u1"])
        self.assertEqual(result.metadata["duration_seconds"], 0.0)
        self.assertTrue(any("0 秒" in w for w in result.warnings))
        self.assertEqual(len(result.timeline["fixed_5min"]), 1)
        self.assertEqual(result.timeline["sliding_5min"], [])
        json.dumps(result.to_dict(), allow_nan=False)

    def test_single_speaker_multiple_utterances_ok_with_limitations(self):
        us = [
            _u("u1", 10.0, "我先梳理题目要求和输入限制", uid="t1"),
            _u("u1", 70.0, "接着看看动态规划状态转移怎么写", uid="t2"),
        ]
        gca = analyze_utterances("m1", us)
        self.assertEqual(gca.status, AnalysisStatus.SINGLE_SPEAKER)

        result = analyze_behavioral("m1", us, gca_result=gca)
        self.assertEqual(result.status, "ok")
        self.assertIsNone(result.metadata["group_distribution"]["normalized_entropy"])
        # 单人发言不输出跨成员 social_impact，但保留 communication_density
        self.assertNotIn("social_impact", result.student_metrics["u1"])
        self.assertIn("communication_density", result.student_metrics["u1"])
        self.assertTrue(any("只有一名有效发言人" in w for w in result.warnings))

    def test_short_class_less_than_one_sliding_step(self):
        us = [_u("u1", 5.0, uid="t1"), _u("u2", 20.0, uid="t2")]
        result = analyze_behavioral("m1", us)
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.timeline["fixed_5min"]), 1)
        self.assertEqual(result.timeline["sliding_5min"], [])
        self.assertTrue(any("不足一个滑动更新点" in w for w in result.warnings))
        self.assertTrue(any("较短" in w for w in result.warnings))

    def test_supplied_duration_behavior(self):
        us = [_u("u1", 10.0, uid="t1"), _u("u2", 120.0, uid="t2")]
        longer = analyze_behavioral("m1", us, duration_seconds=600.0)
        self.assertEqual(longer.metadata["duration_seconds"], 600.0)
        self.assertEqual(longer.metadata["duration_source"], "provided")
        self.assertEqual(len(longer.timeline["fixed_5min"]), 2)
        self.assertAlmostEqual(longer.student_metrics["u1"]["utterances_per_minute"], 0.1)

        shorter = analyze_behavioral("m1", us, duration_seconds=60.0)
        self.assertEqual(shorter.metadata["duration_seconds"], 120.0)
        self.assertTrue(any("小于有效发言最晚时刻" in w for w in shorter.warnings))


class TestBehavioralTimelineAndProtocol(unittest.TestCase):
    def test_timeline_matches_windows_py_boundaries_exactly(self):
        # 覆盖空中间窗口 [300, 600)、边界 t=300、以及非 30 整数倍结尾 t=700
        us = [
            _u("u1", 10.0, uid="t1"),
            _u("u2", 299.0, uid="t2"),
            _u("u3", 600.0, uid="t3"),  # 落在 [600, 900) 而非 [300, 600)
            _u("u1", 700.0, uid="t4"),
        ]
        result = analyze_behavioral("m1", us)
        expected_fixed = build_fixed_windows(us, analyzer=lambda _s: {})
        expected_sliding = build_sliding_windows(us, analyzer=lambda _s: {})

        fixed = result.timeline["fixed_5min"]
        sliding = result.timeline["sliding_5min"]

        self.assertEqual(
            [(w["start_second"], w["end_second"]) for w in fixed],
            [(w["start_second"], w["end_second"]) for w in expected_fixed],
        )
        self.assertEqual(
            [w["center_second"] for w in sliding],
            [w["center_second"] for w in expected_sliding],
        )

        # 固定窗口 0: [0,300) 有 u1、u2；窗口 1: [300,600) 为空；窗口 2: [600,900) 有 u3、u1
        self.assertEqual(fixed[0]["group_metrics"]["participation"]["count"], 2)
        self.assertEqual(fixed[1]["group_metrics"], {})
        self.assertEqual(fixed[1]["student_metrics"], {})
        self.assertEqual(fixed[2]["group_metrics"]["participation"]["count"], 2)

        # 滑动窗口 center=600 覆盖 (300, 600]：只有 t=600 的 u3
        at_600 = next(w for w in sliding if w["center_second"] == 600)
        self.assertEqual(list(at_600["student_metrics"]), ["u3"])
        self.assertEqual(at_600["group_metrics"]["utterance_count"]["mean"], 1.0)
        # 末尾补点 center=700 覆盖 (400, 700]：u3 和 u1
        self.assertEqual(sliding[-1]["center_second"], 700)
        self.assertEqual(sliding[-1]["group_metrics"]["participation"]["count"], 2)

    def test_timeline_disabled(self):
        us = [_u("u1", 10.0, uid="t1"), _u("u2", 60.0, uid="t2")]
        result = analyze_behavioral("m1", us, timeline_enabled=False)
        self.assertIsNone(result.timeline)
        self.assertTrue(any("timeline_enabled=False" in w for w in result.warnings))

    def test_three_dimensions_compose_into_engagement_result(self):
        utterances = [
            _u("u1", 10.0, "我们先讨论排序方案的时间复杂度", uid="t1"),
            _u("u2", 45.0, "我同意，还要对比空间复杂度和边界情况", uid="t2"),
            _u("u1", 95.0, "归并排序最坏情况稳定在 n log n", uid="t3"),
            _u("u2", 150.0, "快速排序原地交换空间开销更小", uid="t4"),
        ]
        gca = analyze_utterances("m1", utterances)
        emotional = analyze_emotional(
            [
                EmotionRecord("m1", "u1", "thinking", 15.0),
                EmotionRecord("m1", "u2", "happy", 50.0),
            ],
            "m1",
        )
        behavioral = analyze_behavioral("m1", utterances, gca_result=gca)
        cognitive = analyze_cognitive(
            "m1",
            utterances,
            [
                SpeechQualityRecord("t1", quality_score=82.0, feedback="观点明确"),
                SpeechQualityRecord("t2", quality_score=86.0, feedback="有效回应同伴"),
            ],
            gca_result=gca,
        )

        merged = EngagementResult(
            meeting_id="m1",
            status=AnalysisStatus.SUCCESS.value,
            dimensions={
                "emotional": emotional,
                "behavioral": behavioral,
                "cognitive": cognitive,
            },
            student_metrics={
                uid: {
                    "emotional": emotional.student_metrics.get(uid, {}),
                    "behavioral": behavioral.student_metrics.get(uid, {}),
                    "cognitive": cognitive.student_metrics.get(uid, {}),
                }
                for uid in ("u1", "u2")
            },
            group_metrics={
                "emotional": emotional.group_metrics,
                "behavioral": behavioral.group_metrics,
                "cognitive": cognitive.group_metrics,
            },
        )
        data = json.loads(json.dumps(merged.to_dict(), allow_nan=False))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["dimensions"]["behavioral"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
