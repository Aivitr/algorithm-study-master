"""维度模块共用的窗口划分与小组统计。

窗口边界与 gca_engine/windows.py 一致：
- 固定窗口 [start, end)，5 分钟一段；
- 滑动窗口 (center-window, center]，30 秒一个更新点。

不直接调用 windows.py 的原因是它的 group_metric_stats 只认 GCA 六指标，
三维模块的自定义指标会被丢弃。
"""

from __future__ import annotations

import math
from typing import Any

from gca_engine.config import (
    FIXED_WINDOW_SECONDS,
    SLIDING_STEP_SECONDS,
    SLIDING_WINDOW_SECONDS,
)

Record = dict[str, Any]


def group_metric_stats(student_metrics: dict[str, dict]) -> dict:
    """按 mean/min/max/std/count 汇总任意数值指标，无数据时返回 {}。"""
    if not student_metrics:
        return {}

    metric_names = sorted(
        {
            name
            for metrics in student_metrics.values()
            for name, value in metrics.items()
            if isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        }
    )
    result = {}
    for name in metric_names:
        values = [
            float(metrics[name])
            for metrics in student_metrics.values()
            if name in metrics
            and isinstance(metrics[name], (int, float))
            and not isinstance(metrics[name], bool)
            and math.isfinite(float(metrics[name]))
        ]
        if not values:
            continue
        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        result[name] = {
            "mean": float(mean),
            "min": float(min(values)),
            "max": float(max(values)),
            "std": float(math.sqrt(variance)),
            "count": len(values),
        }
    return result


def fixed_windows(
    records: list[Record],
    duration: float,
    window_seconds: int = FIXED_WINDOW_SECONDS,
) -> list[tuple[float, float, list[Record]]]:
    """按 [start, end) 划分固定窗口。"""
    max_timestamp = max((float(item["timestamp"]) for item in records), default=0.0)
    # 最后一条记录恰好落在边界上时，也为它保留后一个窗口。
    n_by_records = int(max_timestamp // window_seconds) + 1
    n_by_duration = max(1, int(math.ceil(duration / window_seconds)))
    n_windows = max(1, n_by_records, n_by_duration)

    windows = []
    for index in range(n_windows):
        start = float(index * window_seconds)
        end = float((index + 1) * window_seconds)
        subset = [item for item in records if start <= float(item["timestamp"]) < end]
        windows.append((start, end, subset))
    return windows


def sliding_windows(
    records: list[Record],
    duration: float,
    window_seconds: int = SLIDING_WINDOW_SECONDS,
    step_seconds: int = SLIDING_STEP_SECONDS,
) -> list[tuple[float, list[Record]]]:
    """按 (center-window, center] 划分滑动窗口。"""
    centers: list[float] = []
    point = float(step_seconds)
    while point <= duration:
        centers.append(point)
        point += step_seconds

    if not centers:
        return []
    if duration > centers[-1]:
        centers.append(float(duration))

    result = []
    for center in centers:
        start = max(0.0, center - window_seconds)
        subset = [item for item in records if start < float(item["timestamp"]) <= center]
        result.append((center, subset))
    return result
