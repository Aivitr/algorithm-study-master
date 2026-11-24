"""
gca_engine.engagement.integration —— 三维学习投入统一整合入口（组长：陈虹宇）。

一次调用情感 / 行为 / 认知三个维度模块，把三个 EngagementDimensionResult
投影成统一的 EngagementResult，不重复计算任何指标（投影规则见
docs/engagement_protocol.md 第 5 节）。

口径约定：

- dimensions 三键齐全，缺任一键即校验失败（protocols.EngagementResult 保证）。
- student_metrics 投影：{user_id: {维度名: 指标}}；某个维度没有该学生数据时
  不出现该维度键（与协议 5.2"group_metrics 不出现 emotional 键"同一规则）。
- group_metrics 投影：{维度名: {指标名: 统计}}；某个维度无小组数据时不出现该维度键。
- timeline：整合层本轮不输出（None）；各维度时间趋势经
  dimensions[维度名].timeline 读取。
- 整体 status 沿用 AnalysisStatus 7 种：无发言记录 / 发言清洗后全为空
  → insufficient_data；只有一名发言人 → single_speaker；其余 → success。
  单维度 unavailable / insufficient 不影响整体 status，其余维度照常返回。
- 输入不合法抛 ValueError（由各维度模块校验并向上传播）；数据不足不抛异常。
"""

from __future__ import annotations

from gca_engine.engagement.behavioral import analyze_behavioral
from gca_engine.engagement.cognitive import analyze_cognitive
from gca_engine.engagement.emotional import analyze_emotional
from gca_engine.engagement.protocols import (
    ENGAGEMENT_PROTOCOL_VERSION,
    EmotionRecord,
    EngagementResult,
    SpeechQualityRecord,
)
from gca_engine.engine import ENGINE_VERSION
from gca_engine.preprocessing.chinese import normalize_text
from gca_engine.schemas import AnalysisStatus, GroupAnalysisResult, Utterance


def _validate_inputs(
    meeting_id: str,
    utterances: list[Utterance],
    emotion_records: list[EmotionRecord] | None,
    quality_records: list[SpeechQualityRecord] | None,
) -> None:
    if not isinstance(meeting_id, str) or not meeting_id.strip():
        raise ValueError("meeting_id 必须是非空字符串")
    if not isinstance(utterances, list) or not all(isinstance(u, Utterance) for u in utterances):
        raise ValueError("utterances 必须是 Utterance 列表")
    if emotion_records is not None and (
        not isinstance(emotion_records, list)
        or not all(isinstance(r, EmotionRecord) for r in emotion_records)
    ):
        raise ValueError("emotion_records 必须是 EmotionRecord 列表或 None")
    if quality_records is not None and (
        not isinstance(quality_records, list)
        or not all(isinstance(r, SpeechQualityRecord) for r in quality_records)
    ):
        raise ValueError("quality_records 必须是 SpeechQualityRecord 列表或 None")


def _overall_status(
    utterances: list[Utterance],
    valid_utterances: list[Utterance],
) -> tuple[str, str | None, list[str]]:
    """按协议 5.3 / 5.4 判定整体状态；warning 由调用方并入总 warnings。

    发言人数按清洗后非空的发言统计，与引擎 n_speakers 口径一致。
    """
    if not utterances:
        return (
            AnalysisStatus.INSUFFICIENT_DATA.value,
            "没有任何发言记录",
            [],
        )
    if not valid_utterances:
        return (
            AnalysisStatus.INSUFFICIENT_DATA.value,
            "所有发言清洗后均为空文本，无法计算任何维度",
            [],
        )
    if len({u.speaker_id for u in valid_utterances}) == 1:
        return (
            AnalysisStatus.SINGLE_SPEAKER.value,
            None,
            ["只有一名学生发言：回应类指标受限"],
        )
    return AnalysisStatus.SUCCESS.value, None, []


def _project_student_metrics(dimensions: dict) -> dict:
    """{user_id: {维度名: 指标}}；无该维度数据的学生不出现该维度键。"""
    user_ids = sorted({uid for dim in dimensions.values() for uid in dim.student_metrics})
    projected: dict[str, dict] = {}
    for uid in user_ids:
        entry = {
            name: dim.student_metrics[uid]
            for name, dim in dimensions.items()
            if uid in dim.student_metrics
        }
        if entry:
            projected[uid] = entry
    return projected


def _project_group_metrics(dimensions: dict) -> dict:
    """{维度名: 小组统计}；无小组数据的维度不出现（协议 5.2）。"""
    return {name: dim.group_metrics for name, dim in dimensions.items() if dim.group_metrics}


def analyze_engagement(
    meeting_id: str,
    utterances: list[Utterance],
    emotion_records: list[EmotionRecord] | None = None,
    quality_records: list[SpeechQualityRecord] | None = None,
    gca_result: GroupAnalysisResult | None = None,
    *,
    duration_seconds: float | None = None,
) -> EngagementResult:
    """一次调用三个维度模块，投影出统一的三维学习投入结果。

    Args:
        meeting_id: 讨论小组 ID，与 Utterance.meeting_id 同一口径。
        utterances: 当前小组的统一 Utterance 列表（行为与认知维度共用）。
        emotion_records: 可选情绪记录；None / 空列表 → 情感维度 unavailable。
        quality_records: 可选发言质量评分；None / 空列表按认知模块规则降级。
        gca_result: 可选既有 GroupAnalysisResult（同一批发言），
            行为与认知维度会校验批次一致性后复用，不一致时安全降级。
        duration_seconds: 可选真实课堂时长（课堂相对秒数），透传给
            情感与行为维度；未提供时各维度自行按记录估算。

    Returns:
        EngagementResult：dimensions 三键齐全；整体 status 见模块 docstring。

    非法输入抛 ValueError；数据不足不抛异常，按维度/整体状态降级。
    """
    _validate_inputs(meeting_id, utterances, emotion_records, quality_records)

    dimensions = {
        "emotional": analyze_emotional(
            emotion_records or [], meeting_id, duration_seconds=duration_seconds
        ),
        "behavioral": analyze_behavioral(
            meeting_id, utterances, gca_result=gca_result, duration_seconds=duration_seconds
        ),
        "cognitive": analyze_cognitive(
            meeting_id, utterances, quality_records or [], gca_result=gca_result
        ),
    }

    valid_utterances = [u for u in utterances if normalize_text(u.text)]
    status, error, overall_warnings = _overall_status(utterances, valid_utterances)
    warnings = overall_warnings + [
        warning
        for name in ("emotional", "behavioral", "cognitive")
        for warning in dimensions[name].warnings
    ]

    return EngagementResult(
        meeting_id=meeting_id,
        status=status,
        dimensions=dimensions,
        student_metrics=_project_student_metrics(dimensions),
        group_metrics=_project_group_metrics(dimensions),
        timeline=None,
        metadata={
            "dimension_status": {name: dim.status for name, dim in dimensions.items()},
            "engine_version": ENGINE_VERSION,
            "protocol_version": ENGAGEMENT_PROTOCOL_VERSION,
            "n_utterances": len(utterances),
            "n_valid_utterances": len(valid_utterances),
            "n_speakers": len({u.speaker_id for u in valid_utterances}),
            "n_emotion_records": len(emotion_records or []),
            "n_quality_records": len(quality_records or []),
        },
        warnings=warnings,
        error=error,
    )
