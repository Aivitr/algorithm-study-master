"""
情感投入维度测试（负责人：岳柔）。

测试内容：
1. 正常情绪记录分析
2. 情绪分布统计
3. 无数据处理
4. 非法输入校验
5. 输出结构与 JSON 序列化

遵循 docs/engagement_protocol.md 公共协议。
"""

import json
import unittest

from gca_engine.engagement.emotional import analyze_emotional

from gca_engine.engagement.protocols import EmotionRecord


def _record(user_id, emotion_type, timestamp):
    """创建一条情绪记录。"""
    return EmotionRecord(
        meeting_id="m1",
        user_id=user_id,
        emotion_type=emotion_type,
        timestamp=float(timestamp),
        intensity=0.8,
        source="video",
    )


class TestAnalyzeEmotional(unittest.TestCase):
    def _normal_records(self):
        """构造两名学生的正常情绪记录。"""
        return [
            _record("u001", "happy", 10),
            _record("u001", "happy", 30),
            _record("u001", "calm", 60),
            _record("u001", "thinking", 90),
            _record("u001", "excited", 120),
            _record("u001", "happy", 150),
            _record("u002", "calm", 20),
            _record("u002", "thinking", 50),
            _record("u002", "happy", 80),
            _record("u002", "sad", 110),
            _record("u002", "calm", 140),
            _record("u002", "happy", 170),
        ]

    def test_normal_analysis(self):
        """正常数据应返回情感投入维度结果。"""
        result = analyze_emotional(
            self._normal_records(),
            meeting_id="m1",
        )

        self.assertEqual(result.dimension, "emotional")
        self.assertEqual(result.status, "ok")
        self.assertIsInstance(result.student_metrics, dict)
        self.assertIsInstance(result.group_metrics, dict)

        self.assertIn("u001", result.student_metrics)
        self.assertIn("u002", result.student_metrics)

    def test_emotion_distribution(self):
        """应当分别统计不同学生的情绪分布。"""
        result = analyze_emotional(
            self._normal_records(),
            meeting_id="m1",
        )

        for user_id, metrics in result.student_metrics.items():
            self.assertIn("dominant_emotion", metrics)
            self.assertIn("record_count", metrics)

            self.assertGreater(metrics["record_count"], 0)

    def test_empty_records(self):
        """没有情绪记录时，应返回 unavailable，而不是抛异常。"""
        result = analyze_emotional([], meeting_id="m1")

        self.assertEqual(result.dimension, "emotional")
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.student_metrics, {})
        self.assertEqual(result.group_metrics, {})
        self.assertIsNone(result.timeline)

    def test_invalid_meeting_id_raises(self):
        """meeting_id 为空时应抛出 ValueError。"""
        with self.assertRaises(ValueError):
            analyze_emotional(
                self._normal_records(),
                meeting_id="",
            )

    def test_invalid_records_type_raises(self):
        """records 不是列表时应抛出 ValueError。"""
        with self.assertRaises(ValueError):
            analyze_emotional(
                "invalid",
                meeting_id="m1",
            )

    def test_record_meeting_id_mismatch_raises(self):
        """情绪记录所属课堂必须与分析课堂一致。"""
        records = [
            EmotionRecord(
                meeting_id="m2",
                user_id="u001",
                emotion_type="happy",
                timestamp=10.0,
            )
        ]

        with self.assertRaises(ValueError):
            analyze_emotional(records, meeting_id="m1")

    def test_result_json_serializable(self):
        """输出必须能够进行严格 JSON 序列化。"""
        result = analyze_emotional(
            self._normal_records(),
            meeting_id="m1",
        )

        data = json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
        )

        restored = json.loads(data)

        self.assertEqual(restored["dimension"], "emotional")
        self.assertIn(
            restored["status"],
            ("ok", "insufficient", "unavailable"),
        )

    def test_expected_emotion_results(self):
        """验证具体情绪次数、比例、主导情绪及小组统计结果。"""
        result = analyze_emotional(
            self._normal_records(),
            meeting_id="m1",
        )

        u001 = result.student_metrics["u001"]
        u002 = result.student_metrics["u002"]

        # 验证学生 u001 的情绪分布
        self.assertEqual(
            u001["emotion_distribution"]["counts"],
            {
                "calm": 1,
                "excited": 1,
                "happy": 3,
                "thinking": 1,
            },
        )
        self.assertEqual(u001["dominant_emotion"], "happy")

        # 验证学生 u002 的情绪分布
        self.assertEqual(
            u002["emotion_distribution"]["counts"],
            {
                "calm": 2,
                "happy": 2,
                "sad": 1,
                "thinking": 1,
            },
        )

        # 出现次数相同时，按字母序确定主导情绪
        self.assertEqual(u002["dominant_emotion"], "calm")

        # 验证小组开心情绪的平均记录数
        self.assertEqual(
            result.group_metrics["emotion_count_happy"]["mean"],
            2.5,
        )

        # 输出具体测试结果
        print("\n========== 情感投入统计结果 ==========")

        for user_id, metrics in result.student_metrics.items():
            distribution = metrics["emotion_distribution"]

            print(f"\n学生：{user_id}")
            print(f"情绪记录总数：{distribution['total']}")
            print(f"主导情绪：{metrics['dominant_emotion']}")

            print("情绪分布：")
            for emotion, count in distribution["counts"].items():
                ratio = distribution["ratios"][emotion]
                print(f"  {emotion}: {count} 次，占比 {ratio:.2%}")

            print(f"时间窗口覆盖率：{metrics['coverage']['coverage_rate']:.2%}")

        print("\n小组统计：")
        print(
            "开心情绪平均记录数：",
            result.group_metrics["emotion_count_happy"]["mean"],
        )
        print("整体分析状态：", result.status)
        print("======================================")


if __name__ == "__main__":
    unittest.main()
