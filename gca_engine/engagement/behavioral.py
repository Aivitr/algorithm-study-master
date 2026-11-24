"""行为投入维度分析（负责人：雷梦琪）。

基于统一 Utterance 列表与可选 GroupAnalysisResult，计算学生级与小组级
基础行为指标，并复用 gca_engine/windows.py 的固定/滑动 5 分钟窗口规则
输出行为时间趋势。

约束：
- 返回 protocols.EngagementDimensionResult（dimension="behavioral"）。
- 不计算未经验证的行为投入综合分；发言少不等于未参与思考或学习投入低。
- 真实课堂适配器当前默认 end_time=None，缺失时跳过发言时长并在 metadata 标注。
- 不修改公共文件 windows.py / aggregation.py，复用窗口边界与小组统计口径。
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from statistics import mean, pstdev

from gca_engine.config import (
    FIXED_WINDOW_SECONDS,
    SLIDING_STEP_SECONDS,
    SLIDING_WINDOW_SECONDS,
)
from gca_engine.core.participation import participation as compute_participation
from gca_engine.engagement.protocols import (
    EngagementDimensionResult,
    dimension_result,
)
from gca_engine.preprocessing.chinese import normalize_text
from gca_engine.schemas import AnalysisStatus, GroupAnalysisResult, Utterance
from gca_engine.windows import (
    build_fixed_windows,
    build_sliding_windows,
)
from gca_engine.windows import (
    duration_seconds as compute_duration_seconds,
)

_VALID_ANALYSIS_STATUSES = frozenset(status.value for status in AnalysisStatus)
_MIN_UTTERANCES_FOR_OK = 2
_SHORT_CLASS_SECONDS = 60.0
_REUSABLE_GCA_METRICS = ("social_impact", "communication_density")
_EDUCATIONAL_BOUNDARY = (
    "发言次数与频率仅反映可观察的口头参与行为，发言少不等于未参与思考或学习投入低；"
    "未提供在线成员名单时，群体均衡度仅在已知发言人之间计算，本轮不计算行为投入综合分。"
)


def _finite_float(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        if math.isfinite(numeric):
            return numeric
    return None


def _validate_inputs(
    meeting_id: str,
    utterances: list[Utterance],
    gca_result: GroupAnalysisResult | None,
    duration_seconds: float | None,
) -> float | None:
    """校验公共入口契约；非法输入抛 ValueError。"""
    if not isinstance(meeting_id, str) or not meeting_id.strip():
        raise ValueError("meeting_id 必须是非空字符串")
    if not isinstance(utterances, list):
        raise ValueError("utterances 必须是 Utterance 列表")

    supplied_duration: float | None = None
    if duration_seconds is not None:
        parsed = _finite_float(duration_seconds)
        if parsed is None or parsed < 0:
            raise ValueError("duration_seconds 必须是 >= 0 的有限数字或 None")
        supplied_duration = parsed

    seen_ids: set[str] = set()
    for index, utterance in enumerate(utterances):
        if not isinstance(utterance, Utterance):
            raise ValueError(f"utterances[{index}] 必须是 Utterance 对象")
        if utterance.meeting_id != meeting_id:
            raise ValueError(
                f"utterances[{index}] 的 meeting_id 与分析小组不一致："
                f"{utterance.meeting_id!r} != {meeting_id!r}"
            )
        if utterance.utterance_id in seen_ids:
            raise ValueError(f"重复的发言 utterance_id：{utterance.utterance_id}")
        seen_ids.add(utterance.utterance_id)

    if gca_result is not None:
        if not isinstance(gca_result, GroupAnalysisResult):
            raise ValueError("gca_result 必须是 GroupAnalysisResult 或 None")
        if gca_result.meeting_id != meeting_id:
            raise ValueError("GCA 结果的 meeting_id 必须与当前小组一致")
        if gca_result.status not in _VALID_ANALYSIS_STATUSES:
            raise ValueError("GCA 结果的 status 必须是有效的 AnalysisStatus")
        if not isinstance(gca_result.student_metrics, dict):
            raise ValueError("GCA 的 student_metrics 必须是 dict")

    return supplied_duration


def _summarize_metrics(
    student_metrics: dict[str, dict[str, float]],
) -> dict[str, dict[str, float | int]]:
    """按 aggregation.py 同口径汇总自定义数值指标：mean/min/max/std/count（ddof=0）。"""
    values_by_metric: dict[str, list[float]] = defaultdict(list)
    for metrics in student_metrics.values():
        for name, value in metrics.items():
            values_by_metric[name].append(value)

    return {
        name: {
            "mean": float(mean(values)),
            "min": float(min(values)),
            "max": float(max(values)),
            "std": float(pstdev(values)),
            "count": len(values),
        }
        for name, values in sorted(values_by_metric.items())
    }


def _normalized_entropy(shares: list[float]) -> float | None:
    """活跃发言人之间的归一化香农熵 H / ln(k)，范围 [0, 1]；单人返回 None。"""
    k = len(shares)
    if k < 2:
        return None
    entropy = -sum(p * math.log(p) for p in shares if p > 0.0)
    return float(min(1.0, max(0.0, entropy / math.log(k))))


def _student_base_metrics(
    utterances: list[Utterance],
    span_seconds: float,
    participation_override: dict[str, float] | None = None,
) -> dict[str, dict[str, float]]:
    """计算一组发言中每个活跃学生的基础行为指标（整节课与单窗口共用）。"""
    if not utterances:
        return {}

    counts = Counter(u.speaker_id for u in utterances)
    shares = participation_override or compute_participation([u.speaker_id for u in utterances])
    durations_by_speaker: dict[str, float] = {}
    for utterance in utterances:
        if utterance.end_time is not None:
            durations_by_speaker[utterance.speaker_id] = durations_by_speaker.get(
                utterance.speaker_id, 0.0
            ) + float(utterance.end_time - utterance.timestamp)

    span_minutes = span_seconds / 60.0 if span_seconds > 0.0 else 0.0
    student_metrics: dict[str, dict[str, float]] = {}
    for speaker_id in sorted(counts):
        count = counts[speaker_id]
        entry: dict[str, float] = {
            "utterance_count": float(count),
            "participation": float(shares[speaker_id]),
        }
        if span_minutes > 0.0:
            entry["utterances_per_minute"] = float(count / span_minutes)
        if speaker_id in durations_by_speaker:
            entry["speaking_duration_seconds"] = float(durations_by_speaker[speaker_id])
        student_metrics[speaker_id] = entry
    return student_metrics


def _resolve_gca_students(
    gca_result: GroupAnalysisResult | None,
    speaker_ids: list[str],
    n_raw_utterances: int,
) -> tuple[dict[str, dict[str, float]], bool, list[str]]:
    """校验可选 GCA 结果是否可用且与当前发言批次一致。"""
    if gca_result is None:
        return {}, False, []

    warnings: list[str] = []
    if gca_result.status not in (AnalysisStatus.SUCCESS, AnalysisStatus.SINGLE_SPEAKER):
        warnings.append(f"GCA 分析未完整完成（{gca_result.status}），未复用 GCA 指标")
        return {}, False, warnings

    mismatch = False
    if set(gca_result.student_metrics) != set(speaker_ids):
        mismatch = True
        warnings.append("GCA 结果的学生名单与有效发言不一致，已忽略不匹配的 GCA 结果")
    if isinstance(gca_result.metadata, dict):
        gca_n = gca_result.metadata.get("n_utterances")
        if type(gca_n) is int and gca_n != n_raw_utterances:
            mismatch = True
            warnings.append("GCA 结果与输入的发言条数不一致，已忽略不匹配的 GCA 结果")

    if mismatch:
        return {}, True, warnings
    return gca_result.student_metrics, False, warnings


def _build_timeline(
    valid_utterances: list[Utterance],
    duration: float,
    *,
    fixed_window_seconds: int,
    sliding_window_seconds: int,
    sliding_step_seconds: int,
) -> tuple[dict[str, list[dict]], list[str], dict]:
    """复用 windows.py 的固定/滑动窗口边界，计算每窗口行为指标与小组汇总。"""
    # 传入空列表 + duration 直接从 windows.py 获取权威窗口边界与参数校验，避免重复扫描
    fixed_slots = build_fixed_windows([], window_seconds=fixed_window_seconds, duration=duration)
    sliding_slots = build_sliding_windows(
        [],
        window_seconds=sliding_window_seconds,
        step_seconds=sliding_step_seconds,
        duration=duration,
    )

    fixed_entries: list[dict] = []
    for slot in fixed_slots:
        start = int(slot["start_second"])
        end = int(slot["end_second"])
        subset = [u for u in valid_utterances if start <= u.timestamp < end]
        window_students = _student_base_metrics(subset, float(end - start))
        fixed_entries.append(
            {
                "start_second": start,
                "end_second": end,
                "student_metrics": window_students,
                "group_metrics": _summarize_metrics(window_students),
            }
        )

    sliding_entries: list[dict] = []
    for slot in sliding_slots:
        center = int(slot["center_second"])
        start_f = max(0.0, float(center) - sliding_window_seconds)
        subset = [u for u in valid_utterances if start_f < u.timestamp <= center]
        window_students = _student_base_metrics(subset, float(center) - start_f)
        sliding_entries.append(
            {
                "center_second": center,
                "student_metrics": window_students,
                "group_metrics": _summarize_metrics(window_students),
            }
        )

    warnings: list[str] = []
    n_fixed_empty = sum(1 for item in fixed_entries if not item["group_metrics"])
    if n_fixed_empty:
        warnings.append(
            f"固定 {fixed_window_seconds // 60} 分钟窗口中有 {n_fixed_empty} 个窗口没有有效发言"
        )
    if duration < fixed_window_seconds:
        warnings.append(
            f"课堂时长 {duration:g} 秒不足 {fixed_window_seconds // 60} 分钟，固定窗口只有一个"
        )

    if not sliding_entries:
        warnings.append(
            f"课堂时长 {duration:g} 秒不足一个滑动更新点（{sliding_step_seconds} 秒），"
            "sliding_5min 为空"
        )
    else:
        n_sliding_empty = sum(1 for item in sliding_entries if not item["group_metrics"])
        if n_sliding_empty:
            warnings.append(
                f"滑动窗口中有 {n_sliding_empty} 个更新点最近 "
                f"{sliding_window_seconds // 60} 分钟内没有有效发言"
            )

    timeline = {"fixed_5min": fixed_entries, "sliding_5min": sliding_entries}
    timeline_meta = {
        "fixed_window_seconds": fixed_window_seconds,
        "sliding_window_seconds": sliding_window_seconds,
        "sliding_step_seconds": sliding_step_seconds,
        "n_fixed_windows": len(fixed_entries),
        "n_sliding_windows": len(sliding_entries),
    }
    return timeline, warnings, timeline_meta


def analyze_behavioral(
    meeting_id: str,
    utterances: list[Utterance],
    gca_result: GroupAnalysisResult | None = None,
    *,
    duration_seconds: float | None = None,
    fixed_window_seconds: int = FIXED_WINDOW_SECONDS,
    sliding_window_seconds: int = SLIDING_WINDOW_SECONDS,
    sliding_step_seconds: int = SLIDING_STEP_SECONDS,
    timeline_enabled: bool = True,
) -> EngagementDimensionResult:
    """分析一节课的行为投入维度，返回统一的 EngagementDimensionResult。"""
    supplied_duration = _validate_inputs(meeting_id, utterances, gca_result, duration_seconds)

    ordered = sorted(utterances, key=lambda u: (u.timestamp, u.utterance_id))
    valid_utterances = [u for u in ordered if normalize_text(u.text)]
    n_empty = len(ordered) - len(valid_utterances)
    warnings: list[str] = []
    if n_empty > 0:
        warnings.append(f"有 {n_empty} 条发言清洗后为空文本，已从行为指标统计中排除")

    if not valid_utterances:
        error_msg = (
            "没有任何发言记录" if not utterances else "所有发言清洗后均为空文本，无法计算行为指标"
        )
        return dimension_result(
            "behavioral",
            "unavailable",
            metadata={
                "n_utterances": len(utterances),
                "n_valid_utterances": 0,
                "empty_text_count": n_empty,
                "n_speakers": 0,
                "duration_seconds": float(supplied_duration or 0.0),
                "speaking_duration_available": False,
                "end_time_coverage": 0.0,
                "composite_score_calculated": False,
                "educational_boundary": _EDUCATIONAL_BOUNDARY,
            },
            warnings=warnings,
            error=error_msg,
        )

    n_valid = len(valid_utterances)
    speaker_ids = sorted({u.speaker_id for u in valid_utterances})
    single_speaker = len(speaker_ids) == 1

    # 1. 可选 GCA 指标复用（仅批次一致时复用；无空文本过滤时直接复用 GCA participation）
    gca_students, gca_mismatch, gca_warnings = _resolve_gca_students(
        gca_result, speaker_ids, len(utterances)
    )
    warnings.extend(gca_warnings)

    participation_override: dict[str, float] | None = None
    participation_source = "utterances"
    reused_gca_metrics: set[str] = set()
    if gca_students and n_empty == 0:
        parsed = {
            uid: _finite_float(gca_students.get(uid, {}).get("participation"))
            for uid in speaker_ids
        }
        if all(val is not None for val in parsed.values()):
            participation_override = {uid: val for uid, val in parsed.items() if val is not None}
            participation_source = "gca_result"
            reused_gca_metrics.add("participation")

    # 2. 观察时长与发言时长覆盖情况
    inferred_duration = compute_duration_seconds(valid_utterances)
    if supplied_duration is not None:
        if supplied_duration < inferred_duration:
            warnings.append(
                f"传入课堂时长（{supplied_duration:g} 秒）小于有效发言最晚时刻"
                f"（{inferred_duration:g} 秒），已取较大值以覆盖全部有效发言"
            )
        duration = max(inferred_duration, supplied_duration)
        duration_source = "provided"
    else:
        duration = inferred_duration
        duration_source = "utterances_estimate"

    if duration <= 0.0:
        warnings.append("有效观察时长为 0 秒，无法计算发言频率（utterances_per_minute）")
    elif duration < _SHORT_CLASS_SECONDS:
        warnings.append(
            f"有效观察时长较短（{duration:g} 秒 < 60 秒），每分钟发言频率波动较大，解读时需谨慎"
        )

    n_with_end_time = sum(1 for u in valid_utterances if u.end_time is not None)
    if n_with_end_time == 0:
        warnings.append("发言记录缺少 end_time，发言时长指标已降级跳过（本轮仅统计次数与频率）")
    elif n_with_end_time < n_valid:
        warnings.append(
            f"仅 {n_with_end_time}/{n_valid} 条有效发言提供 end_time，"
            "speaking_duration_seconds 为部分覆盖统计"
        )

    # 3. 学生级基础指标 + 可选 GCA 补充指标
    student_metrics = _student_base_metrics(
        valid_utterances, duration, participation_override=participation_override
    )
    if gca_students:
        for uid, metrics in student_metrics.items():
            for metric_name in _REUSABLE_GCA_METRICS:
                if metric_name == "social_impact" and single_speaker:
                    continue
                val = _finite_float(gca_students.get(uid, {}).get(metric_name))
                if val is not None:
                    metrics[metric_name] = val
                    reused_gca_metrics.add(metric_name)

    if single_speaker:
        warnings.append(
            "只有一名有效发言人：个体发言计数与频率已计算，但群体参与均衡度与社会影响力缺少比较对象"
        )

    # 4. 小组汇总与群体参与分布
    group_metrics = _summarize_metrics(student_metrics)
    shares_list = [student_metrics[uid]["participation"] for uid in speaker_ids]
    group_distribution = {
        "active_speaker_count": len(speaker_ids),
        "total_utterances": n_valid,
        "participation_std": float(pstdev(shares_list)),
        "max_participation_share": float(max(shares_list)),
        "normalized_entropy": _normalized_entropy(shares_list),
    }

    # 5. 固定/滑动时间窗口趋势
    timeline: dict[str, list[dict]] | None = None
    timeline_meta: dict = {}
    if timeline_enabled:
        timeline, timeline_warnings, timeline_meta = _build_timeline(
            valid_utterances,
            duration,
            fixed_window_seconds=fixed_window_seconds,
            sliding_window_seconds=sliding_window_seconds,
            sliding_step_seconds=sliding_step_seconds,
        )
        warnings.extend(timeline_warnings)
    else:
        warnings.append("timeline 已按 timeline_enabled=False 关闭")

    # 6. 状态判定（与协议 5.1 / 5.4 一致）
    error: str | None = None
    if n_valid < _MIN_UTTERANCES_FOR_OK:
        status = "insufficient"
        error = "有效发言少于 2 条，行为指标样本不足，已保留可计算的基础统计"
        warnings.append("有效发言少于 2 条，行为指标稳定性受限")
    else:
        status = "ok"

    return dimension_result(
        "behavioral",
        status,
        student_metrics=student_metrics,
        group_metrics=group_metrics,
        timeline=timeline,
        metadata={
            "n_utterances": len(utterances),
            "n_valid_utterances": n_valid,
            "empty_text_count": n_empty,
            "n_speakers": len(speaker_ids),
            "duration_seconds": float(duration),
            "duration_source": duration_source,
            "speaking_duration_available": n_with_end_time > 0,
            "end_time_coverage": float(n_with_end_time / n_valid),
            "participation_source": participation_source,
            "gca_reused": bool(reused_gca_metrics),
            "gca_reused_metrics": sorted(reused_gca_metrics),
            "gca_mismatch": gca_mismatch,
            "group_distribution": group_distribution,
            "timeline": timeline_meta,
            "composite_score_calculated": False,
            "educational_boundary": _EDUCATIONAL_BOUNDARY,
        },
        warnings=warnings,
        error=error,
    )
