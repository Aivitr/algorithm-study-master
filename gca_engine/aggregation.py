"""
gca_engine.aggregation —— 学生指标 → 小组指标（负责人：雷梦琪）。

group_metric_stats: 对六个指标分别统计全体学生的
mean / min / max / std / count。

v0.1 约定：不计算任何"团队综合分"。
"""

import numpy as np

from gca_engine.schemas import SIX_METRICS


def group_metric_stats(
    student_metrics: dict[str, dict[str, float]],
) -> dict[str, dict[str, float]]:
    """把学生六指标汇总成小组六指标统计。

    Args:
        student_metrics: {speaker_id: {六个指标: 值}}。

    Returns:
        {指标名: {"mean": ..., "min": ..., "max": ..., "std": ..., "count": ...}}。
        没有学生时返回 {}。
    """
    if not student_metrics:
        return {}

    out: dict[str, dict[str, float]] = {}
    for metric in SIX_METRICS:
        values = np.asarray(
            [m[metric] for m in student_metrics.values()], dtype=float
        )
        out[metric] = {
            "mean": float(values.mean()),
            "min": float(values.min()),
            "max": float(values.max()),
            "std": float(values.std()),
            "count": int(values.size),
        }
    return out
