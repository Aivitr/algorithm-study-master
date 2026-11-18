"""认知投入基础指标，复用已有 GCA 结果和上游发言质量评分。"""

from collections import Counter, defaultdict
from math import isfinite
from statistics import mean, pstdev

from gca_engine.engagement.protocols import (
    EngagementDimensionResult,
    SpeechQualityRecord,
    dimension_result,
)
from gca_engine.preprocessing.chinese import normalize_text
from gca_engine.schemas import AnalysisStatus, GroupAnalysisResult, Utterance

_GCA_METRICS = ("overall_responsivity", "newness", "internal_cohesion")
# 对应 app/realtime/speech.py 和 stream.py 的评分状态文本。
_PENDING_OR_FAILED = {"评估中", "已断句，正在评分", "评估超时"}
_QUALITY_LIMITATION = (
    "评分记录没有来源标志。缺少反馈、反馈表示处理中或超时、"
    "以及仅有‘已评估’反馈的 0 分或 50 分均不计入，可能遗漏真实评分。"
)


def _validate_inputs(
    meeting_id: str,
    utterances: list[Utterance],
    quality: list[SpeechQualityRecord],
    gca_result: GroupAnalysisResult | None,
) -> None:
    if not isinstance(meeting_id, str) or not meeting_id.strip():
        raise ValueError("meeting_id 必须是非空字符串")
    if not isinstance(utterances, list) or not all(isinstance(u, Utterance) for u in utterances):
        raise ValueError("utterances 必须是 Utterance 列表")
    if not isinstance(quality, list) or not all(
        isinstance(r, SpeechQualityRecord) for r in quality
    ):
        raise ValueError("quality 必须是 SpeechQualityRecord 列表")

    utterance_ids = set()
    for utterance in utterances:
        Utterance.__post_init__(utterance)
        if utterance.meeting_id != meeting_id:
            raise ValueError("发言的 meeting_id 必须与当前小组一致")
        if utterance.utterance_id in utterance_ids:
            raise ValueError(f"重复的发言 utterance_id：{utterance.utterance_id}")
        utterance_ids.add(utterance.utterance_id)

    quality_ids = set()
    for record in quality:
        if not isinstance(record.utterance_id, str) or not record.utterance_id.strip():
            raise ValueError("评分的 utterance_id 必须是非空字符串")
        if record.utterance_id in quality_ids:
            raise ValueError(f"重复的评分 utterance_id：{record.utterance_id}")
        quality_ids.add(record.utterance_id)
        if record.feedback is not None and not isinstance(record.feedback, str):
            raise ValueError("评分的 feedback 必须是字符串或 None")
        if record.quality_score is not None and (
            not isinstance(record.quality_score, (int, float))
            or isinstance(record.quality_score, bool)
        ):
            raise ValueError("quality_score 必须是数字或 None")

    if gca_result is None:
        return
    if not isinstance(gca_result, GroupAnalysisResult):
        raise ValueError("gca_result 必须是 GroupAnalysisResult 或 None")
    if gca_result.meeting_id != meeting_id:
        raise ValueError("GCA 结果的 meeting_id 必须与当前小组一致")
    if gca_result.status not in tuple(AnalysisStatus):
        raise ValueError("GCA 结果的 status 必须是有效的 AnalysisStatus")
    if not isinstance(gca_result.student_metrics, dict) or any(
        not isinstance(user_id, str) or not user_id.strip() or not isinstance(metrics, dict)
        for user_id, metrics in gca_result.student_metrics.items()
    ):
        raise ValueError("GCA 的 student_metrics 必须以非空字符串学生 ID 映射到指标字典")


def _has_valid_quality(record: SpeechQualityRecord) -> bool:
    score = record.quality_score
    # 范围比较同时排除 NaN 和无穷值。
    if score is None or not 0 <= score <= 100:
        return False
    feedback = (record.feedback or "").strip().rstrip(".。…").strip()
    if not feedback or feedback in _PENDING_OR_FAILED:
        return False
    # “已评估”也用于上游兜底，无法确认这两个分值的来源。
    return not (feedback == "已评估" and score in (0, 50))


def _gca_metrics_for_student(metrics: dict, single_speaker: bool) -> dict[str, float]:
    extracted = {}
    for name in _GCA_METRICS:
        if name == "overall_responsivity" and single_speaker:
            continue
        value = metrics.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            # 引擎输出 float，允许手工构造的结果使用可表示的整数。
            try:
                value = float(value)
            except OverflowError:
                continue
            if isfinite(value):
                extracted[name] = value
    return extracted


def _summarize_metrics(student_metrics: dict[str, dict[str, float]]) -> dict:
    values_by_metric = defaultdict(list)
    for metrics in student_metrics.values():
        for name, value in metrics.items():
            values_by_metric[name].append(value)
    return {
        name: {
            "mean": mean(values),
            "min": min(values),
            "max": max(values),
            "std": pstdev(values),
            "count": len(values),
        }
        for name, values in values_by_metric.items()
    }


def analyze_cognitive(
    meeting_id: str,
    utterances: list[Utterance],
    quality: list[SpeechQualityRecord],
    gca_result: GroupAnalysisResult | None = None,
) -> EngagementDimensionResult:
    """汇总认知投入代理指标和质量评分。代理指标间接描述讨论特征。"""
    _validate_inputs(meeting_id, utterances, quality, gca_result)
    # 与课堂适配器一致，清洗后为空的转写不纳入评分覆盖率分母。
    speaker_by_utterance = {
        u.utterance_id: u.speaker_id for u in utterances if normalize_text(u.text)
    }
    utterance_counts = Counter(speaker_by_utterance.values())
    warnings = []
    if len(speaker_by_utterance) < len(utterances):
        warnings.append("已排除清洗后为空的发言。")

    gca_students = {}
    gca_status = gca_result.status if gca_result is not None else None
    if gca_status in (
        AnalysisStatus.SUCCESS,
        AnalysisStatus.SINGLE_SPEAKER,
        AnalysisStatus.INSUFFICIENT_DATA,
    ):
        gca_students = gca_result.student_metrics
    if gca_status is None:
        warnings.append("未提供 GCA 结果。")
    elif gca_status not in (AnalysisStatus.SUCCESS, AnalysisStatus.SINGLE_SPEAKER):
        warnings.append(f"GCA 分析未完整完成（{gca_status}）。")

    # 只有 GCA 结果时可保留已存在的指标，但无法关联评分或确认发言样本。
    student_ids = utterance_counts.keys() if utterances else gca_students.keys()
    single_speaker = len(student_ids) == 1 or gca_status == AnalysisStatus.SINGLE_SPEAKER
    if single_speaker:
        warnings.append("只有一名有效发言人，跨学生回应性缺少比较对象。")
    gca_mismatch = False
    if utterances and gca_students.keys() - utterance_counts.keys():
        gca_mismatch = True
        warnings.append("GCA 结果中缺少对应有效发言的学生未纳入统计。")
    if utterances and gca_result is not None and isinstance(gca_result.metadata, dict):
        # 引擎的 n_utterances 包含清洗后为空的条目，与原始输入数量比较。
        gca_utterance_count = gca_result.metadata.get("n_utterances")
        if type(gca_utterance_count) is int and gca_utterance_count != len(utterances):
            gca_mismatch = True
            warnings.append("GCA 结果与输入的发言条数不一致，请核对是否来自同一批发言。")

    scores_by_speaker = defaultdict(list)
    unmatched_count = 0
    excluded_count = 0
    for record in quality:
        speaker = speaker_by_utterance.get(record.utterance_id)
        if speaker is None:
            unmatched_count += 1
        elif _has_valid_quality(record):
            scores_by_speaker[speaker].append(record.quality_score)
        else:
            excluded_count += 1

    if unmatched_count:
        warnings.append(f"{unmatched_count} 条评分未匹配到有效发言。")
    if excluded_count:
        warnings.append(f"{excluded_count} 条已匹配评分因缺失、超范围或来源无法确认而排除。")

    student_metrics = {}
    gca_counts = dict.fromkeys(_GCA_METRICS, 0)
    for user_id in student_ids:
        metrics = _gca_metrics_for_student(gca_students.get(user_id, {}), single_speaker)
        for name in metrics:
            gca_counts[name] += 1
        if metrics:
            student_metrics[user_id] = metrics

    # 没有任何可用代理指标或质量分时，只在元数据中记录零覆盖。
    if student_metrics or scores_by_speaker:
        for user_id, utterance_count in utterance_counts.items():
            metrics = student_metrics.setdefault(user_id, {})
            scores = scores_by_speaker.get(user_id, [])
            metrics["quality_count"] = len(scores)
            metrics["quality_coverage"] = len(scores) / utterance_count
            if scores:
                metrics["quality_mean"] = mean(scores)

    n_valid_utterances = len(speaker_by_utterance)
    n_scores = sum(len(scores) for scores in scores_by_speaker.values())
    if n_scores < n_valid_utterances:
        warnings.append("部分有效发言缺少可用质量评分。")
    incomplete_metrics = [name for name, count in gca_counts.items() if count < len(student_ids)]
    if incomplete_metrics:
        warnings.append(f"GCA 指标未覆盖全部学生：{', '.join(incomplete_metrics)}。")

    # 首版状态按输入和字段可用性判定，部分评分缺失时不使用百分比阈值。
    error = None
    if not n_valid_utterances and not student_metrics:
        status = "unavailable"
        error = "没有有效发言或可用的认知代理指标。"
    elif gca_mismatch:
        status = "insufficient"
        error = "GCA 结果和输入发言不一致，已保留可匹配指标。"
    elif (
        gca_status != AnalysisStatus.SUCCESS or single_speaker or incomplete_metrics or not n_scores
    ):
        status = "insufficient"
        error = "认知代理指标或发言质量评分不足，已保留可用指标。"
    else:
        status = "ok"

    return dimension_result(
        "cognitive",
        status,
        student_metrics=student_metrics,
        group_metrics=_summarize_metrics(student_metrics),
        metadata={
            "n_utterances": len(utterances),
            "n_valid_utterances": n_valid_utterances,
            "n_speakers": len(student_ids),
            "n_quality_records": len(quality),
            "n_valid_quality_scores": n_scores,
            "n_unmatched_quality_records": unmatched_count,
            "n_excluded_quality_records": excluded_count,
            "quality_coverage": n_scores / n_valid_utterances if n_valid_utterances else None,
            "quality_validity_limitation": _QUALITY_LIMITATION,
            "gca_metric_student_counts": gca_counts,
        },
        warnings=warnings,
        error=error,
    )
