"""行为投入维度分析。

只统计发言次数、参与比例和单位时间发言频率；未接入动作/摄像头数据。
可选复用 GCA 的 social_impact / communication_density 作为互动代理，
不重新计算 GCA 指标，也不输出行为投入综合分。
"""

from __future__ import annotations

import math
from collections import Counter

from gca_engine.config import (
    FIXED_WINDOW_SECONDS,
    SLIDING_STEP_SECONDS,
    SLIDING_WINDOW_SECONDS,
)
from gca_engine.engagement._common import (
    fixed_windows,
    group_metric_stats,
    sliding_windows,
)
from gca_engine.engagement.protocols import EngagementDimensionResult, dimension_result
from gca_engine.preprocessing.chinese import normalize_text
from gca_engine.schemas import AnalysisStatus, GroupAnalysisResult, Utterance

# 可直接复用为互动代理的 GCA 六指标（不重算）。
_INTERACTION_METRICS = ("social_impact", "communication_density")
_USABLE_GCA_STATUSES = (
    AnalysisStatus.SUCCESS,
    AnalysisStatus.SINGLE_SPEAKER,
    AnalysisStatus.INSUFFICIENT_DATA,
)


def _validate_inputs(
    meeting_id: str,
    utterances: list[Utterance],
    gca_result: GroupAnalysisResult | None,
) -> None:
    if not isinstance(meeting_id, str) or not meeting_id.strip():
        raise ValueError("meeting_id 必须是非空字符串")
    if not isinstance(utterances, list):
        raise ValueError("utterances 必须是 Utterance 列表")
    for index, utterance in enumerate(utterances):
        if not isinstance(utterance, Utterance):
            raise ValueError(f"utterances[{index}] 必须是 Utterance")
        if utterance.meeting_id != meeting_id:
            raise ValueError(
                f"utterances[{index}] 的 meeting_id 与分析课堂不一致："
                f"{utterance.meeting_id!r} != {meeting_id!r}"
            )
    if gca_result is not None:
        if not isinstance(gca_result, GroupAnalysisResult):
            raise ValueError("gca_result 必须是 GroupAnalysisResult 或 None")
        if gca_result.meeting_id != meeting_id:
            raise ValueError(
                f"gca_result.meeting_id 与分析课堂不一致："
                f"{gca_result.meeting_id!r} != {meeting_id!r}"
            )


def _window_student_metrics(records: list[dict]) -> dict:
    counts = Counter(item["user_id"] for item in records)
    total = len(records)
    return {
        user_id: {
            "utterance_count": float(count),
            "participation": float(count / total),
        }
        for user_id, count in sorted(counts.items())
    }


def _window_group_metrics(records: list[dict]) -> dict:
    return group_metric_stats(_window_student_metrics(records))


def analyze_behavioral(
    meeting_id: str,
    utterances: list[Utterance],
    gca_result: GroupAnalysisResult | None = None,
) -> EngagementDimensionResult:
    """分析一节课的行为维度，返回统一的 EngagementDimensionResult。"""
    _validate_inputs(meeting_id, utterances, gca_result)

    records: list[dict] = []
    empty_count = 0
    for utterance in utterances:
        if not normalize_text(utterance.text):
            empty_count += 1
            continue
        records.append(
            {
                "user_id": utterance.speaker_id,
                "timestamp": float(utterance.timestamp),
                "utterance_id": utterance.utterance_id,
                "end_time": utterance.end_time,
            }
        )

    warnings = []
    if empty_count:
        warnings.append(f"已排除 {empty_count} 条清洗后为空的发言。")

    if not records:
        return dimension_result(
            "behavioral",
            "unavailable",
            metadata={
                "n_utterances": len(utterances),
                "n_valid_utterances": 0,
                "n_excluded_empty": empty_count,
                "action_data_available": False,
            },
            warnings=warnings,
            error="没有任何发言记录",
        )

    records.sort(key=lambda item: (item["timestamp"], item["user_id"]))
    total = len(records)
    duration = max(
        float(item["end_time"]) if item["end_time"] is not None else float(item["timestamp"])
        for item in records
    )
    counts = Counter(item["user_id"] for item in records)
    minutes = duration / 60.0

    student_metrics: dict[str, dict] = {}
    for user_id in sorted(counts):
        metrics = {
            "utterance_count": float(counts[user_id]),
            "participation": float(counts[user_id] / total),
        }
        if minutes > 0:
            metrics["utterances_per_minute"] = float(counts[user_id] / minutes)
        student_metrics[user_id] = metrics

    gca_status = gca_result.status if gca_result is not None else None
    gca_reused_students = 0
    if gca_result is not None and gca_status in _USABLE_GCA_STATUSES:
        for user_id, metrics in gca_result.student_metrics.items():
            if user_id not in student_metrics:
                continue
            reused = False
            for name in _INTERACTION_METRICS:
                value = metrics.get(name)
                if (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(float(value))
                ):
                    student_metrics[user_id][f"gca_{name}"] = float(value)
                    reused = True
            if reused:
                gca_reused_students += 1

    if len(student_metrics) == 1:
        warnings.append("当前仅有一名学生发言，小组分布不代表全体学生。")
    if gca_result is None:
        warnings.append("未提供 GCA 结果，未输出互动代理指标。")
    elif gca_status not in _USABLE_GCA_STATUSES:
        warnings.append(f"GCA 分析未完整完成（{gca_status}），未复用互动代理指标。")

    status = "ok" if total >= 2 else "insufficient"
    error = None
    if status == "insufficient":
        error = "有效发言少于 2 条，已输出可用计数，但数据不足以支持稳定判断。"

    fixed_timeline = []
    for start, end, subset in fixed_windows(records, duration):
        fixed_timeline.append(
            {
                "start_second": int(start),
                "end_second": int(end),
                "student_metrics": _window_student_metrics(subset),
                "group_metrics": _window_group_metrics(subset),
            }
        )
    sliding_timeline = []
    for center, subset in sliding_windows(records, duration):
        sliding_timeline.append(
            {
                "center_second": int(center),
                "student_metrics": _window_student_metrics(subset),
                "group_metrics": _window_group_metrics(subset),
            }
        )

    return dimension_result(
        "behavioral",
        status,
        student_metrics=student_metrics,
        group_metrics=group_metric_stats(student_metrics),
        timeline={
            "fixed_5min": fixed_timeline,
            "sliding_5min": sliding_timeline,
        },
        metadata={
            "meeting_id": meeting_id,
            "n_utterances": len(utterances),
            "n_valid_utterances": total,
            "n_excluded_empty": empty_count,
            "n_speakers": len(student_metrics),
            "duration_seconds": float(duration),
            "duration_source": "max_utterance_end_or_timestamp",
            "window_seconds": FIXED_WINDOW_SECONDS,
            "sliding_window_seconds": SLIDING_WINDOW_SECONDS,
            "sliding_step_seconds": SLIDING_STEP_SECONDS,
            "gca_status": gca_status,
            "gca_interaction_students": gca_reused_students,
            "action_data_available": False,
            "composite_score_calculated": False,
        },
        warnings=warnings,
        error=error,
    )
