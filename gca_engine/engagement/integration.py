"""三维学习投入整合入口。

按公共协议把情感、行为、认知三个维度结果投影成 EngagementResult，
不重复计算指标，也不输出 E_e/E_b/E_c 综合分。
"""

from __future__ import annotations

from gca_engine.engagement.behavioral import analyze_behavioral
from gca_engine.engagement.cognitive import analyze_cognitive
from gca_engine.engagement.emotional import analyze_emotional
from gca_engine.engagement.protocols import (
    EmotionRecord,
    EngagementResult,
    SpeechQualityRecord,
)
from gca_engine.preprocessing.chinese import normalize_text
from gca_engine.schemas import AnalysisStatus, GroupAnalysisResult, Utterance

PROTOCOL_VERSION = "1.0"


def _overall_status(utterances: list[Utterance]) -> tuple[str, str | None, list[str]]:
    valid = [utterance for utterance in utterances if normalize_text(utterance.text)]
    speakers = {utterance.speaker_id for utterance in valid}
    if not valid:
        return AnalysisStatus.INSUFFICIENT_DATA.value, "没有任何发言记录", []
    if len(valid) < 2:
        return (
            AnalysisStatus.INSUFFICIENT_DATA.value,
            "有效发言少于 2 条，三维结果仅供参考",
            [],
        )
    if len(speakers) == 1:
        return (
            AnalysisStatus.SINGLE_SPEAKER.value,
            None,
            ["只有一名学生发言：回应类指标受限"],
        )
    return AnalysisStatus.SUCCESS.value, None, []


def analyze_engagement(
    meeting_id: str,
    utterances: list[Utterance],
    emotions: list[EmotionRecord] | None = None,
    quality: list[SpeechQualityRecord] | None = None,
    gca_result: GroupAnalysisResult | None = None,
    *,
    duration_seconds: float | None = None,
) -> EngagementResult:
    """整合一节课的三维投入。

    数据不足/不可用不抛异常，通过状态与维度 error 表达；
    输入结构不合法（如 meeting_id 不一致）抛 ValueError。
    """
    if not isinstance(meeting_id, str) or not meeting_id.strip():
        raise ValueError("meeting_id 必须是非空字符串")
    if not isinstance(utterances, list):
        raise ValueError("utterances 必须是 Utterance 列表")
    emotions = emotions or []
    quality = quality or []
    if not isinstance(emotions, list):
        raise ValueError("emotions 必须是 EmotionRecord 列表")
    if not isinstance(quality, list):
        raise ValueError("quality 必须是 SpeechQualityRecord 列表")

    dimensions = {
        "emotional": analyze_emotional(emotions, meeting_id, duration_seconds=duration_seconds),
        "behavioral": analyze_behavioral(meeting_id, utterances, gca_result=gca_result),
        "cognitive": analyze_cognitive(meeting_id, utterances, quality, gca_result=gca_result),
    }

    status, error, warnings = _overall_status(utterances)

    student_metrics: dict[str, dict] = {}
    for name, result in dimensions.items():
        for user_id, metrics in result.student_metrics.items():
            student_metrics.setdefault(user_id, {})[name] = metrics
    group_metrics = {
        name: result.group_metrics for name, result in dimensions.items() if result.group_metrics
    }

    for result in dimensions.values():
        warnings.extend(result.warnings)

    return EngagementResult(
        meeting_id=meeting_id,
        status=status,
        dimensions=dimensions,
        student_metrics=student_metrics,
        group_metrics=group_metrics,
        metadata={
            "protocol_version": PROTOCOL_VERSION,
            "dimension_status": {name: result.status for name, result in dimensions.items()},
            "n_utterances": len(utterances),
            "n_speakers": len(
                {utterance.speaker_id for utterance in utterances if normalize_text(utterance.text)}
            ),
            "gca_status": gca_result.status if gca_result is not None else None,
            "composite_score_calculated": False,
        },
        warnings=list(dict.fromkeys(warnings)),
        error=error,
    )
