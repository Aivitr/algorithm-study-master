"""Deterministic collaboration signals derived from GCA results.

This module deliberately contains no database access and no LLM calls.  It
turns already-computed GCA metrics into conservative, explainable classroom
observations for the teacher dashboard.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable

MIN_UTTERANCES_FOR_SIGNALS = 8
MIN_SPEAKERS_FOR_IMBALANCE = 4
TOP_TWO_PARTICIPATION_WARNING = 0.65
TREND_DROP_WARNING = 0.10


def _signal(
    signal_type: str,
    level: str,
    title: str,
    description: str,
    suggestion: str,
    *,
    evidence: Dict[str, Any] | None = None,
    related_student_ids: Iterable[str] = (),
) -> Dict[str, Any]:
    return {
        "type": signal_type,
        "level": level,
        "title": title,
        "description": description,
        "evidence": evidence or {},
        "suggestion": suggestion,
        "related_student_ids": [str(item) for item in related_student_ids],
    }


def _valid_fixed_windows(gca_result: Dict[str, Any]) -> list[Dict[str, Any]]:
    timeline = gca_result.get("timeline") or {}
    return [
        window
        for window in timeline.get("fixed_5min", [])
        if isinstance(window, dict) and window.get("group_metrics")
    ]


def _metric_mean(window: Dict[str, Any], metric: str) -> float | None:
    stats = (window.get("group_metrics") or {}).get(metric) or {}
    value = stats.get("mean")
    return float(value) if isinstance(value, (int, float)) else None


def build_collaboration_signals(gca_result: Dict[str, Any]) -> list[Dict[str, Any]]:
    """Build conservative teacher-facing observations from a GCA result."""
    status = str(gca_result.get("status") or "internal_error")
    metadata = gca_result.get("metadata") or {}
    student_metrics = gca_result.get("student_metrics") or {}
    utterance_count = int(metadata.get("n_utterances") or 0)
    speaker_count = int(metadata.get("n_speakers") or len(student_metrics))

    if status == "empty_transcript":
        return [
            _signal(
                "no_data",
                "info",
                "暂无学生发言",
                "当前还没有可用于协作分析的学生发言。",
                "等待学生产生有效讨论后再刷新分析。",
            )
        ]
    if status == "single_speaker":
        return [
            _signal(
                "single_speaker",
                "info",
                "目前只有一名学生发言",
                "单人数据不足以判断群体回应和相互影响。",
                "可先邀请其他成员表达观点，再观察协作变化。",
                evidence={"speaker_count": speaker_count, "utterance_count": utterance_count},
            )
        ]
    if status != "success":
        return [
            _signal(
                "insufficient_data",
                "info",
                "当前数据暂不足以判断",
                str(gca_result.get("error") or "协作指标暂未形成稳定结果。"),
                "继续讨论并积累更多有效发言后再刷新。",
                evidence={"status": status},
            )
        ]

    signals: list[Dict[str, Any]] = []
    if utterance_count < MIN_UTTERANCES_FOR_SIGNALS:
        signals.append(
            _signal(
                "limited_sample",
                "info",
                "数据仍在积累",
                f"当前共有 {utterance_count} 条有效发言，指标可能随新发言明显变化。",
                "将当前结果作为观察线索，不作为学生评价结论。",
                evidence={"utterance_count": utterance_count},
            )
        )
        return signals

    participation = sorted(
        (
            (str(student_id), float(metrics.get("participation") or 0.0))
            for student_id, metrics in student_metrics.items()
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    if len(participation) >= MIN_SPEAKERS_FOR_IMBALANCE:
        top_two_share = sum(value for _, value in participation[:2])
        if top_two_share >= TOP_TWO_PARTICIPATION_WARNING:
            top_students = [student_id for student_id, _ in participation[:2]]
            signals.append(
                _signal(
                    "participation_imbalance",
                    "warning",
                    "参与分布较集中",
                    f"当前前两名发言者承担了约 {top_two_share * 100:.0f}% 的发言。",
                    "可考虑安排一轮依次表达，为其他成员留出发言空间。",
                    evidence={
                        "top_two_share": round(top_two_share, 4),
                        "speaker_count": speaker_count,
                        "utterance_count": utterance_count,
                    },
                    related_student_ids=top_students,
                )
            )

    windows = _valid_fixed_windows(gca_result)
    if len(windows) >= 2:
        previous, current = windows[-2], windows[-1]
        for metric, signal_type, title, description, suggestion in (
            (
                "overall_responsivity",
                "responsivity_decline",
                "同伴回应有所减少",
                "最近两个有效时间段中，回应同伴指标出现下降。",
                "可请成员先复述或评价上一位同学的观点，再补充自己的意见。",
            ),
            (
                "newness",
                "newness_decline",
                "新观点贡献有所减少",
                "最近两个有效时间段中，新观点贡献指标出现下降。",
                "可增加反例、约束条件或新的比较角度，帮助讨论继续推进。",
            ),
        ):
            old_value = _metric_mean(previous, metric)
            new_value = _metric_mean(current, metric)
            if old_value is None or new_value is None:
                continue
            drop = old_value - new_value
            if drop >= TREND_DROP_WARNING:
                signals.append(
                    _signal(
                        signal_type,
                        "warning",
                        title,
                        description,
                        suggestion,
                        evidence={
                            "previous_mean": round(old_value, 4),
                            "current_mean": round(new_value, 4),
                            "drop": round(drop, 4),
                            "previous_window": {
                                "start_second": previous.get("start_second"),
                                "end_second": previous.get("end_second"),
                            },
                            "current_window": {
                                "start_second": current.get("start_second"),
                                "end_second": current.get("end_second"),
                            },
                        },
                    )
                )

    if not signals:
        signals.append(
            _signal(
                "no_obvious_signal",
                "success",
                "暂未发现明显协作异常",
                "当前数据没有触发参与集中或趋势下降规则。",
                "可继续观察后续时间段的变化。",
                evidence={"speaker_count": speaker_count, "utterance_count": utterance_count},
            )
        )
    return signals
