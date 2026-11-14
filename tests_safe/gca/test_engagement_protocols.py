"""
第二阶段公共协议测试（组长：陈虹宇）。

覆盖：DIMENSION_STATUS / DIMENSIONS / HINT_TYPES 的取值、
EmotionRecord / SpeechQualityRecord / EngagementDimensionResult /
EngagementResult / HintCandidate 的创建与校验、五类样例的 JSON 序列化。
详细口径见 docs/engagement_protocol.md。
"""

import json
import unittest

from gca_engine.engagement.protocols import (
    DIMENSIONS,
    DIMENSION_STATUS,
    HINT_TYPES,
    TARGET_TYPES,
    EmotionRecord,
    EngagementDimensionResult,
    EngagementResult,
    HintCandidate,
    SpeechQualityRecord,
    dimension_result,
)


def _ok_dimension(name: str, metric: str = "positive_ratio") -> EngagementDimensionResult:
    return dimension_result(
        name,
        "ok",
        student_metrics={"u001": {metric: 0.6}},
        group_metrics={metric: {"mean": 0.6, "min": 0.6, "max": 0.6, "std": 0.0, "count": 1}},
    )


class TestConstants(unittest.TestCase):

    def test_dimensions_exactly_three(self):
        self.assertEqual(DIMENSIONS, ("emotional", "behavioral", "cognitive"))

    def test_dimension_status_exactly_three(self):
        self.assertEqual(DIMENSION_STATUS, ("ok", "insufficient", "unavailable"))

    def test_hint_types_exactly_two(self):
        self.assertEqual(HINT_TYPES, ("low_participation", "discussion_stall"))

    def test_target_types(self):
        self.assertEqual(TARGET_TYPES, ("student", "group"))


class TestEmotionRecord(unittest.TestCase):

    def test_create_basic(self):
        r = EmotionRecord("m1", "u001", "happy", 12.5, intensity=0.8, source="video")
        self.assertEqual(r.to_dict()["emotion_type"], "happy")
        self.assertEqual(r.to_dict()["intensity"], 0.8)

    def test_empty_meeting_id_raises(self):
        with self.assertRaises(ValueError):
            EmotionRecord("", "u001", "happy", 1.0)

    def test_empty_user_id_raises(self):
        with self.assertRaises(ValueError):
            EmotionRecord("m1", " ", "happy", 1.0)

    def test_empty_emotion_type_raises(self):
        with self.assertRaises(ValueError):
            EmotionRecord("m1", "u001", "", 1.0)

    def test_negative_timestamp_raises(self):
        with self.assertRaises(ValueError):
            EmotionRecord("m1", "u001", "happy", -1.0)

    def test_nonfinite_timestamp_raises(self):
        with self.assertRaises(ValueError):
            EmotionRecord("m1", "u001", "happy", float("nan"))

    def test_nonfinite_intensity_raises(self):
        with self.assertRaises(ValueError):
            EmotionRecord("m1", "u001", "happy", 1.0, intensity=float("inf"))


class TestSpeechQualityRecord(unittest.TestCase):

    def test_create_basic(self):
        r = SpeechQualityRecord("t1", quality_score=85.0, relevance_score=3.0)
        self.assertEqual(r.to_dict()["quality_score"], 85.0)

    def test_empty_utterance_id_raises(self):
        with self.assertRaises(ValueError):
            SpeechQualityRecord("")

    def test_nonfinite_score_raises(self):
        with self.assertRaises(ValueError):
            SpeechQualityRecord("t1", quality_score=float("nan"))

    def test_none_scores_allowed(self):
        r = SpeechQualityRecord("t1")
        self.assertIsNone(r.quality_score)
        self.assertIsNone(r.relevance_score)


class TestEngagementDimensionResult(unittest.TestCase):

    def test_ok_result(self):
        r = _ok_dimension("behavioral", "utterance_count")
        self.assertEqual(r.status, "ok")
        self.assertEqual(r.timeline, None)
        self.assertEqual(r.error, None)

    def test_invalid_dimension_raises(self):
        with self.assertRaises(ValueError):
            _ok_dimension("wrong")

    def test_invalid_status_raises(self):
        # 维度状态不允许用整体状态的 success —— 两套状态体系不能混
        with self.assertRaises(ValueError):
            dimension_result("emotional", "success")

    def test_unavailable_result_is_empty_not_none(self):
        r = dimension_result("emotional", "unavailable", error="课堂未开启情绪识别")
        self.assertEqual(r.student_metrics, {})
        self.assertEqual(r.group_metrics, {})
        self.assertIsNone(r.timeline)
        self.assertEqual(r.error, "课堂未开启情绪识别")


class TestEngagementResult(unittest.TestCase):

    def test_all_three_dimensions_required(self):
        with self.assertRaises(ValueError):
            EngagementResult(
                meeting_id="m1",
                status="success",
                dimensions={"emotional": _ok_dimension("emotional")},
                student_metrics={},
                group_metrics={},
            )

    def test_dimensions_none_raises(self):
        # dimensions=None 属于非法输入，必须抛 ValueError 而不是 TypeError
        with self.assertRaises(ValueError):
            EngagementResult(meeting_id="m1", status="success", dimensions=None)

    def test_status_must_be_analysis_status(self):
        # 整体状态必须用 AnalysisStatus 7 种，不能用 ok/insufficient
        with self.assertRaises(ValueError):
            EngagementResult(
                meeting_id="m1",
                status="ok",
                dimensions={d: _ok_dimension(d) for d in DIMENSIONS},
                student_metrics={},
                group_metrics={},
            )

    def test_round_trip_serializable(self):
        result = EngagementResult(
            meeting_id="m1",
            status="success",
            dimensions={d: _ok_dimension(d) for d in DIMENSIONS},
            student_metrics={"u001": {"behavioral": {"utterance_count": 3.0}}},
            group_metrics={"behavioral": {"utterance_count": {
                "mean": 3.0, "min": 3.0, "max": 3.0, "std": 0.0, "count": 1}}},
            metadata={"generated_at": "2026-11-14T00:00:00+00:00"},
        )
        data = json.loads(json.dumps(result.to_dict(), allow_nan=False))
        self.assertEqual(data["meeting_id"], "m1")
        self.assertEqual(sorted(data["dimensions"]), sorted(DIMENSIONS))


class TestHintCandidate(unittest.TestCase):

    def _candidate(self, **kwargs):
        base = dict(
            meeting_id="m1",
            hint_type="low_participation",
            target_type="student",
            target_user_id="u001",
            window={"start_second": 30.0, "end_second": 330.0},
            trigger_reason="最近窗口内 0 次发言",
            evidence={"self_utterances": 0},
            data_status="ok",
            generated_at=330.0,
            dedupe_key="low_participation:m1:student:u001",
        )
        base.update(kwargs)
        return HintCandidate(**base)

    def test_student_requires_target_user_id(self):
        with self.assertRaises(ValueError):
            self._candidate(target_user_id=None)

    def test_group_target_user_id_must_be_none(self):
        with self.assertRaises(ValueError):
            self._candidate(target_type="group", target_user_id="u001")

    def test_invalid_hint_type_raises(self):
        with self.assertRaises(ValueError):
            self._candidate(hint_type="cognitive_deepening")

    def test_invalid_data_status_raises(self):
        with self.assertRaises(ValueError):
            self._candidate(data_status="success")

    def test_window_bounds_validated(self):
        with self.assertRaises(ValueError):
            self._candidate(window={"start_second": 330.0, "end_second": 30.0})

    def test_window_values_must_be_numeric(self):
        # window 的值必须是有限数字，字符串即使能比较大小也不能通过校验
        with self.assertRaises(ValueError):
            self._candidate(window={"start_second": "30", "end_second": 330.0})

    def test_serializable(self):
        data = json.loads(json.dumps(self._candidate().to_dict(), allow_nan=False))
        self.assertEqual(data["hint_type"], "low_participation")


class TestSampleScenarios(unittest.TestCase):
    """任务文档要求的五类样例：必须能通过校验并被 JSON 序列化。"""

    def _merged(self, dimensions):
        student_metrics = {}
        group_metrics = {}
        for dim_result in dimensions.values():
            if dim_result.status != "ok":
                continue
            for uid, metrics in dim_result.student_metrics.items():
                student_metrics.setdefault(uid, {})[dim_result.dimension] = metrics
            group_metrics[dim_result.dimension] = dim_result.group_metrics
        status = (
            "success"
            if any(d.status == "ok" for d in dimensions.values())
            else "insufficient_data"
        )
        return EngagementResult(
            meeting_id="m1",
            status=status,
            dimensions=dimensions,
            student_metrics=student_metrics,
            group_metrics=group_metrics,
        )

    def test_scenario1_normal_all_dimensions(self):
        result = self._merged({d: _ok_dimension(d) for d in DIMENSIONS})
        data = json.loads(json.dumps(result.to_dict(), allow_nan=False))
        self.assertEqual(data["status"], "success")
        self.assertEqual(set(data["group_metrics"]), set(DIMENSIONS))

    def test_scenario2_one_dimension_missing(self):
        dims = {d: _ok_dimension(d) for d in DIMENSIONS}
        dims["emotional"] = dimension_result(
            "emotional", "unavailable", error="课堂未开启情绪识别"
        )
        result = self._merged(dims)
        data = json.loads(json.dumps(result.to_dict(), allow_nan=False))
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["dimensions"]["emotional"]["status"], "unavailable")
        self.assertNotIn("emotional", data["group_metrics"])

    def test_scenario3_no_speech(self):
        dims = {
            d: dimension_result(d, "unavailable", error="没有任何发言记录")
            for d in DIMENSIONS
        }
        result = self._merged(dims)
        data = json.loads(json.dumps(result.to_dict(), allow_nan=False))
        self.assertEqual(data["status"], "insufficient_data")
        self.assertEqual(data["student_metrics"], {})

    def test_scenario4_single_speaker(self):
        # 单人课堂：发言类维度能算，但比较类指标受限，由各模块在 metadata 说明
        dims = {
            "emotional": _ok_dimension("emotional"),
            "behavioral": _ok_dimension("behavioral", "utterance_count"),
            "cognitive": dimension_result(
                "cognitive", "insufficient",
                metadata={"n_speakers": 1},
                error="只有一名发言人，回应类指标无比较对象",
            ),
        }
        result = self._merged(dims)
        result.status = "single_speaker"
        data = json.loads(json.dumps(result.to_dict(), allow_nan=False))
        self.assertEqual(data["status"], "single_speaker")
        self.assertEqual(data["dimensions"]["cognitive"]["status"], "insufficient")

    def test_scenario5_partial_metrics_no_composite_score(self):
        # 部分指标可用但不计算综合分：本轮不输出 E_e/E_b/E_c
        dims = {
            "emotional": dimension_result(
                "emotional", "insufficient",
                student_metrics={"u001": {"positive_ratio": 0.5}},
                group_metrics={"positive_ratio": {
                    "mean": 0.5, "min": 0.5, "max": 0.5, "std": 0.0, "count": 1}},
                metadata={"coverage": 0.2},
                error="情绪记录覆盖不足，未计算综合分",
            ),
            "behavioral": _ok_dimension("behavioral", "utterance_count"),
            "cognitive": dimension_result(
                "cognitive", "insufficient",
                metadata={"quality_score_coverage": 0.3},
                error="质量评分缺失较多，未计算综合分",
            ),
        }
        result = self._merged(dims)
        data = json.loads(json.dumps(result.to_dict(), allow_nan=False))
        self.assertEqual(data["status"], "success")
        self.assertNotIn("composite_score", data["dimensions"]["emotional"]["metadata"])
        self.assertEqual(data["dimensions"]["emotional"]["status"], "insufficient")


if __name__ == "__main__":
    unittest.main()
