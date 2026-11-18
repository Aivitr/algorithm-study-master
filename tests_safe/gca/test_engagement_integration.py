"""三维投入整合入口测试：状态、投影与维度缺失。"""

import json
import unittest

from gca_engine.engagement import analyze_engagement
from gca_engine.engagement.protocols import EmotionRecord, SpeechQualityRecord
from gca_engine.schemas import AnalysisStatus, GroupAnalysisResult, Utterance


def _utterance(speaker, timestamp, text="发言内容", uid=None):
    return Utterance(
        meeting_id="m1",
        speaker_id=speaker,
        text=text,
        timestamp=float(timestamp),
        utterance_id=uid or f"{speaker}-{timestamp}",
    )


def _emotion(user_id, timestamp):
    return EmotionRecord(
        meeting_id="m1",
        user_id=user_id,
        emotion_type="happy",
        timestamp=float(timestamp),
    )


class TestAnalyzeEngagement(unittest.TestCase):
    def test_three_dimensions_are_projected(self):
        utterances = [
            _utterance("u1", 10, uid="1"),
            _utterance("u2", 20, uid="2"),
            _utterance("u1", 30, uid="3"),
        ]
        quality = [
            SpeechQualityRecord(utterance_id="1", quality_score=80, feedback="已评估"),
            SpeechQualityRecord(utterance_id="2", quality_score=70, feedback="已评估"),
            SpeechQualityRecord(utterance_id="3", quality_score=90, feedback="已评估"),
        ]
        emotions = [_emotion("u1", 10), _emotion("u2", 20)]

        result = analyze_engagement("m1", utterances, emotions=emotions, quality=quality)

        self.assertEqual(result.status, AnalysisStatus.SUCCESS.value)
        self.assertEqual(set(result.dimensions), {"emotional", "behavioral", "cognitive"})
        self.assertEqual(
            set(result.student_metrics["u1"]), {"emotional", "behavioral", "cognitive"}
        )
        self.assertEqual(set(result.group_metrics), {"emotional", "behavioral", "cognitive"})
        self.assertFalse(result.metadata["composite_score_calculated"])
        self.assertEqual(result.metadata["dimension_status"]["behavioral"], "ok")
        json.dumps(result.to_dict(), allow_nan=False)

    def test_no_utterances_returns_insufficient_data(self):
        result = analyze_engagement("m1", [])

        self.assertEqual(result.status, AnalysisStatus.INSUFFICIENT_DATA.value)
        self.assertEqual(result.dimensions["behavioral"].status, "unavailable")
        self.assertEqual(result.dimensions["cognitive"].status, "unavailable")
        self.assertEqual(result.student_metrics, {})
        self.assertEqual(result.error, "没有任何发言记录")

    def test_one_utterance_is_insufficient_data(self):
        result = analyze_engagement("m1", [_utterance("u1", 10)])
        self.assertEqual(result.status, AnalysisStatus.INSUFFICIENT_DATA.value)
        self.assertIsNotNone(result.error)

    def test_single_speaker_status_and_warning(self):
        result = analyze_engagement("m1", [_utterance("u1", 10), _utterance("u1", 20)])

        self.assertEqual(result.status, AnalysisStatus.SINGLE_SPEAKER.value)
        self.assertTrue(any("只有一名学生" in item for item in result.warnings))
        self.assertIsNone(result.error)

    def test_missing_emotions_does_not_block_other_dimensions(self):
        result = analyze_engagement("m1", [_utterance("u1", 10), _utterance("u2", 20)])

        self.assertEqual(result.dimensions["emotional"].status, "unavailable")
        self.assertEqual(result.dimensions["behavioral"].status, "ok")
        self.assertNotIn("emotional", result.group_metrics)
        self.assertEqual(result.status, AnalysisStatus.SUCCESS.value)

    def test_gca_result_is_passed_to_both_dimensions(self):
        gca = GroupAnalysisResult(
            meeting_id="m1",
            status=AnalysisStatus.SUCCESS.value,
            student_metrics={
                "u1": {
                    "participation": 0.5,
                    "social_impact": 0.3,
                    "overall_responsivity": 0.4,
                },
                "u2": {
                    "participation": 0.5,
                    "social_impact": 0.2,
                    "overall_responsivity": 0.5,
                },
            },
            group_metrics={},
        )
        result = analyze_engagement(
            "m1",
            [_utterance("u1", 10), _utterance("u2", 20)],
            gca_result=gca,
        )

        self.assertIn("gca_social_impact", result.student_metrics["u1"]["behavioral"])
        self.assertIn("overall_responsivity", result.student_metrics["u1"]["cognitive"])
        self.assertEqual(result.metadata["gca_status"], AnalysisStatus.SUCCESS.value)

    def test_meeting_mismatch_raises(self):
        other = Utterance(
            meeting_id="m2",
            speaker_id="u1",
            text="x",
            timestamp=1.0,
            utterance_id="1",
        )
        with self.assertRaises(ValueError):
            analyze_engagement("m1", [other])

    def test_warnings_are_deduplicated(self):
        result = analyze_engagement("m1", [_utterance("u1", 10), _utterance("u1", 20)])
        self.assertEqual(len(result.warnings), len(set(result.warnings)))


if __name__ == "__main__":
    unittest.main()
