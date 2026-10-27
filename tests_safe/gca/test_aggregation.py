"""
小组汇总统计测试（负责人：雷梦琪）。
"""

import unittest

from gca_engine.aggregation import group_metric_stats


class TestGroupMetricStats(unittest.TestCase):

    def _full_metrics(self, participation, newness):
        """补齐六个指标（聚合的输入契约：每个学生必须有完整六指标）。"""
        return {
            "participation": participation,
            "internal_cohesion": 0.1,
            "overall_responsivity": 0.1,
            "social_impact": 0.1,
            "newness": newness,
            "communication_density": 0.1,
        }

    def test_stats_over_three_students(self):
        student_metrics = {
            "a": self._full_metrics(0.6, 0.2),
            "b": self._full_metrics(0.2, 0.4),
            "c": self._full_metrics(0.2, 0.9),
        }
        stats = group_metric_stats(student_metrics)
        p = stats["participation"]
        self.assertAlmostEqual(p["mean"], 1.0 / 3.0)
        self.assertAlmostEqual(p["min"], 0.2)
        self.assertAlmostEqual(p["max"], 0.6)
        self.assertEqual(p["count"], 3)
        self.assertGreaterEqual(p["std"], 0.0)

    def test_single_student_std_zero(self):
        stats = group_metric_stats({"a": self._full_metrics(0.5, 0.5)})
        self.assertAlmostEqual(stats["participation"]["std"], 0.0)
        self.assertEqual(stats["participation"]["count"], 1)

    def test_empty_returns_empty(self):
        self.assertEqual(group_metric_stats({}), {})


if __name__ == "__main__":
    unittest.main()
