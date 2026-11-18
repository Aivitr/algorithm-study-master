"""情感投入维度分析。

本模块只统计已有情绪识别记录，不把情绪标签直接解释为情感投入程度，
也不计算情感投入综合分。输入和输出严格遵循 protocols.py 的公共协议。
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict

from gca_engine.config import (
    FIXED_WINDOW_SECONDS,
    SLIDING_STEP_SECONDS,
    SLIDING_WINDOW_SECONDS,
)
from gca_engine.engagement.protocols import (
    EmotionRecord,
    EngagementDimensionResult,
    dimension_result,
)

# 与 app/core/emotions.py 归一化词表一致的项目标准标签。
# 协议约定适配层完成归一化（EmotionRecord.emotion_type 已是归一化标签），
# 本模块只做词表校验，不重复归一化；未知标签不会被擅自当作新情绪类别。
KNOWN_EMOTIONS = frozenset(
    {
        "happy",
        "excited",
        "surprised",
        "calm",
        "neutral",
        "thinking",
        "confused",
        "sad",
        "angry",
    }
)


# 每条学生指标中的基础数值字段。小组汇总按 aggregation.py 的
# mean/min/max/std/count 口径实现，但不调用只识别 SIX_METRICS 的旧函数。
_BASE_NUMERIC_METRICS = ("record_count", "coverage_rate")


def _validate_inputs(records: list[EmotionRecord], meeting_id: str) -> None:
    """校验公共接口输入；结构错误属于非法输入，应抛 ValueError。"""
    if not isinstance(meeting_id, str) or not meeting_id.strip():
        raise ValueError("meeting_id 必须是非空字符串")
    if not isinstance(records, list):
        raise ValueError("records 必须是 EmotionRecord 列表")
    for index, record in enumerate(records):
        if not isinstance(record, EmotionRecord):
            raise ValueError(f"records[{index}] 必须是 EmotionRecord")
        if record.meeting_id != meeting_id:
            raise ValueError(
                f"records[{index}] 的 meeting_id 与分析课堂不一致："
                f"{record.meeting_id!r} != {meeting_id!r}"
            )


def _normalize_records(
    records: list[EmotionRecord],
) -> tuple[list[dict], Counter, list[str]]:
    """校验情绪标签在项目标准词表中，并收集无法识别的标签记录。"""
    normalized: list[dict] = []
    invalid_reasons: Counter = Counter()
    warnings: list[str] = []

    for record in records:
        # 协议规定 emotion_type 已是归一化标签（适配层负责归一化，
        # 见 protocols.EmotionRecord docstring），这里只校验不重复归一化。
        label = record.emotion_type
        if label not in KNOWN_EMOTIONS:
            invalid_reasons["unknown_emotion_label"] += 1
            continue

        normalized.append(
            {
                "meeting_id": record.meeting_id,
                "user_id": record.user_id,
                "emotion_type": label,
                "timestamp": float(record.timestamp),
                "intensity": (float(record.intensity) if record.intensity is not None else None),
                "record_id": record.record_id,
            }
        )

    if invalid_reasons:
        warnings.append(
            f"有 {invalid_reasons['unknown_emotion_label']} 条记录的情绪标签不在项目标准词表中，已跳过"
        )
    return normalized, invalid_reasons, warnings


def _distribution(records: list[dict]) -> dict:
    """计算一个记录集合的情绪计数、比例和主导情绪。"""
    counts = Counter(item["emotion_type"] for item in records)
    total = len(records)
    ratios = {emotion: count / total for emotion, count in sorted(counts.items())} if total else {}
    dominant = None
    if counts:
        # 次数相同时按标签字母序，保证结果可复现。
        dominant = min(counts, key=lambda label: (-counts[label], label))
    return {
        "counts": dict(sorted(counts.items())),
        "ratios": ratios,
        "dominant_emotion": dominant,
        "total": total,
    }


def _numeric_student_metrics(
    records: list[dict],
    coverage_rate: float | None = None,
) -> dict[str, float]:
    """生成可用于小组统计的标量指标。"""
    distribution = _distribution(records)
    metrics: dict[str, float] = {
        "record_count": float(len(records)),
    }
    if coverage_rate is not None:
        metrics["coverage_rate"] = float(coverage_rate)

    for emotion in sorted(KNOWN_EMOTIONS):
        metrics[f"emotion_count_{emotion}"] = float(distribution["counts"].get(emotion, 0))
        metrics[f"emotion_ratio_{emotion}"] = float(distribution["ratios"].get(emotion, 0.0))
    return metrics


def _group_metric_stats(student_metrics: dict[str, dict]) -> dict:
    """按公共协议 aggregation.py 的口径汇总任意自定义数值指标。

    aggregation.group_metric_stats 目前只处理 GCA 的 SIX_METRICS，情绪指标
    不属于那六项，因此在本模块内复用相同统计定义，而不修改公共文件。
    """
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


def _fixed_windows(
    records: list[dict],
    duration: float,
    window_seconds: int = FIXED_WINDOW_SECONDS,
) -> list[dict]:
    """按 windows.py 的固定窗口边界 [start, end) 划分情绪记录。"""
    max_timestamp = max((item["timestamp"] for item in records), default=0.0)
    # 即使最后一条记录恰好落在 300/600 秒边界，也为它保留后一个窗口。
    n_by_records = int(max_timestamp // window_seconds) + 1
    n_by_duration = max(1, int(math.ceil(duration / window_seconds)))
    n_windows = max(1, n_by_records, n_by_duration)

    windows = []
    for index in range(n_windows):
        start = float(index * window_seconds)
        end = float((index + 1) * window_seconds)
        subset = [item for item in records if start <= item["timestamp"] < end]
        windows.append((start, end, subset))
    return windows


def _sliding_windows(
    records: list[dict],
    duration: float,
    window_seconds: int = SLIDING_WINDOW_SECONDS,
    step_seconds: int = SLIDING_STEP_SECONDS,
) -> list[tuple[float, list[dict]]]:
    """按 windows.py 的滑动窗口边界 (center-window, center] 取数。"""
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
        subset = [item for item in records if start < item["timestamp"] <= center]
        result.append((center, subset))
    return result


def _window_student_metrics(records: list[dict]) -> dict:
    """统计当前时间窗口内每个学生的情绪分布和记录数量。"""
    if not records:
        return {}

    by_student: dict[str, list[dict]] = defaultdict(list)

    for item in records:
        by_student[item["user_id"]].append(item)

    result = {}

    for user_id in sorted(by_student):
        student_records = by_student[user_id]
        distribution = _distribution(student_records)

        result[user_id] = {
            "record_count": len(student_records),
            "emotion_distribution": distribution["counts"],
        }

    return result


def _window_group_metrics(records: list[dict]) -> dict:
    """将窗口内记录先按学生统计，再按学生维度汇总为小组指标。"""
    if not records:
        return {}
    by_student: dict[str, list[dict]] = defaultdict(list)
    for item in records:
        by_student[item["user_id"]].append(item)
    per_student = {
        user_id: _numeric_student_metrics(student_records)
        for user_id, student_records in by_student.items()
    }
    return _group_metric_stats(per_student)


def analyze_emotional(
    records: list[EmotionRecord],
    meeting_id: str,
    *,
    duration_seconds: float | None = None,
) -> EngagementDimensionResult:
    """分析一节课的情感维度，返回统一的 EngagementDimensionResult。

    Args:
        records: 当前课堂的 EmotionRecord 列表。
        meeting_id: 当前课堂 ID，必须与每条记录中的 meeting_id 一致。
        duration_seconds: 可选的真实课堂时长（课堂开始后的秒数）。
            上游调用方若能取得 meeting.duration，可传入以改善覆盖率统计；
            未提供时按最后一条有效情绪记录的时间估算观察跨度。

    Returns:
        EngagementDimensionResult。数据不足/不可用不抛异常；非法输入抛 ValueError。
    """
    _validate_inputs(records, meeting_id)

    if duration_seconds is not None:
        if (
            not isinstance(duration_seconds, (int, float))
            or isinstance(duration_seconds, bool)
            or not math.isfinite(float(duration_seconds))
            or duration_seconds < 0
        ):
            raise ValueError("duration_seconds 必须是 >= 0 的有限数字或 None")
        supplied_duration = float(duration_seconds)
    else:
        supplied_duration = None

    if not records:
        return dimension_result(
            "emotional",
            "unavailable",
            error="没有可用的情绪记录（可能未开启情绪识别）",
            metadata={"input_record_count": 0, "valid_record_count": 0},
        )

    normalized, invalid_reasons, warnings = _normalize_records(records)
    if not normalized:
        return dimension_result(
            "emotional",
            "insufficient",
            metadata={
                "input_record_count": len(records),
                "valid_record_count": 0,
                "invalid_record_count": sum(invalid_reasons.values()),
                "invalid_reasons": dict(invalid_reasons),
            },
            warnings=warnings,
            error="输入中没有可识别的标准情绪标签",
        )

    normalized.sort(key=lambda item: (item["timestamp"], item["user_id"]))
    max_timestamp = max(item["timestamp"] for item in normalized)
    duration = max(max_timestamp, supplied_duration or 0.0)
    fixed = _fixed_windows(normalized, duration)
    total_windows = len(fixed)

    by_student: dict[str, list[dict]] = defaultdict(list)
    for item in normalized:
        by_student[item["user_id"]].append(item)

    student_metrics: dict[str, dict] = {}
    for user_id in sorted(by_student):
        student_records = by_student[user_id]
        distribution = _distribution(student_records)
        covered_windows = sum(
            1
            for _start, _end, subset in fixed
            if any(item["user_id"] == user_id for item in subset)
        )
        coverage_rate = covered_windows / total_windows if total_windows else 0.0
        student_metrics[user_id] = {
            "emotion_distribution": distribution,
            "record_count": len(student_records),
            "coverage": {
                "covered_windows": covered_windows,
                "total_windows": total_windows,
                "coverage_rate": float(coverage_rate),
            },
            "dominant_emotion": distribution["dominant_emotion"],
        }
        student_metrics[user_id].update(_numeric_student_metrics(student_records, coverage_rate))

    group_metrics = _group_metric_stats(
        {
            user_id: {
                key: value
                for key, value in metrics.items()
                if key in _BASE_NUMERIC_METRICS
                or key.startswith("emotion_count_")
                or key.startswith("emotion_ratio_")
            }
            for user_id, metrics in student_metrics.items()
        }
    )

    fixed_timeline = []
    for start, end, subset in fixed:
        fixed_timeline.append(
            {
                "start_second": int(start),
                "end_second": int(end),
                "student_metrics": _window_student_metrics(subset),
                "group_metrics": _window_group_metrics(subset),
            }
        )
    sliding_timeline = []
    for center, subset in _sliding_windows(normalized, duration):
        sliding_timeline.append(
            {
                "center_second": int(center),
                "student_metrics": _window_student_metrics(subset),
                "group_metrics": _window_group_metrics(subset),
            }
        )

    valid_count = len(normalized)
    status = "ok" if valid_count >= 2 else "insufficient"
    if status == "insufficient":
        warnings.append("有效情绪记录少于 2 条，已输出可计算的基础统计，但数据不足以支持稳定判断")

    if supplied_duration is None:
        warnings.append(
            "未提供真实课堂总时长；coverage_rate 按有效情绪记录的观察时间跨度估算，不能视为整节课的真实覆盖率"
        )

    if len(student_metrics) == 1:
        warnings.append("当前仅有一名学生存在有效情绪记录，小组分布不代表全体学生")

    group_covered = sum(1 for _start, _end, subset in fixed if subset)
    group_coverage = group_covered / total_windows if total_windows else 0.0

    return dimension_result(
        "emotional",
        status,
        student_metrics=student_metrics,
        group_metrics=group_metrics,
        timeline={
            "fixed_5min": fixed_timeline,
            "sliding_5min": sliding_timeline,
        },
        metadata={
            "meeting_id": meeting_id,
            "input_record_count": len(records),
            "valid_record_count": valid_count,
            "invalid_record_count": sum(invalid_reasons.values()),
            "invalid_reasons": dict(sorted(invalid_reasons.items())),
            "student_count": len(student_metrics),
            "group_coverage": {
                "covered_windows": group_covered,
                "total_windows": total_windows,
                "coverage_rate": float(group_coverage),
            },
            "duration_seconds": float(duration),
            "duration_source": "provided"
            if supplied_duration is not None
            else "max_valid_emotion_timestamp_estimate",
            "window_seconds": FIXED_WINDOW_SECONDS,
            "sliding_window_seconds": SLIDING_WINDOW_SECONDS,
            "sliding_step_seconds": SLIDING_STEP_SECONDS,
            "coverage_definition": (
                "固定5分钟窗口中至少有一条该学生有效情绪记录即视为该学生窗口被覆盖"
            ),
            "coverage_limitation": (
                None
                if supplied_duration is not None
                else "未提供课堂总时长，按最后一条有效情绪记录估算观察跨度"
            ),
            "emotion_labels": sorted(KNOWN_EMOTIONS),
            "intensity_used": False,
            "composite_score_calculated": False,
        },
        warnings=warnings,
        error=None,
    )
