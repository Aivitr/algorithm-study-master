"""
gca_engine.engine —— 把各模块接起来的总流程（负责人：雷梦琪）。

v0.2 流程：

    统一 Utterance 列表
      → 输入检查（invalid_input / empty_transcript / insufficient_data）
      → 按时间排序
      → 文本清洗 + LSA（在本次课堂发言上拟合语义空间）
      → 词数统计（与 LSA 同一种分词，保持旧基线一致）
      → GCA 六指标（core.metrics，数学与旧基线一致）
      → 学生指标 → 小组汇总（aggregation）
      → 时间窗口（windows：固定 5 分钟 + 滑动 5 分钟）
      → GroupAnalysisResult

窗口与整体共用同一个 LSA 语义空间：窗口只切向量子集重算 GCA，
不重新拟合，否则各窗口的语义坐标不一致，时间趋势不可比。
"""

import logging
from datetime import datetime, timezone

from gca_engine.aggregation import group_metric_stats
from gca_engine.config import EngineConfig
from gca_engine.core.config import GCAConfig
from gca_engine.core.lsa import clean_text
from gca_engine.core.lsa import tokenize as legacy_tokenize
from gca_engine.preprocessing.chinese import tokenize as chinese_tokenize
from gca_engine.core.lsa.config import LSAConfig
from gca_engine.core.metrics import compute_gca_metrics
from gca_engine.schemas import (
    AnalysisStatus,
    GroupAnalysisResult,
    Utterance,
)
from gca_engine.semantic import fit_lsa_space, project_texts
from gca_engine.windows import build_timeline, duration_seconds

ENGINE_VERSION = "0.2.0"
logger = logging.getLogger(__name__)


def _error_result(
    meeting_id: str,
    status: AnalysisStatus,
    message: str,
    warnings: list[str] | None = None,
) -> GroupAnalysisResult:
    return GroupAnalysisResult(
        meeting_id=meeting_id,
        status=status,
        student_metrics={},
        group_metrics={},
        timeline=None,
        metadata={},
        warnings=warnings or [],
        error=message,
    )


def _validate(meeting_id: str, utterances: list[Utterance]) -> str | None:
    """返回错误信息；输入没问题时返回 None。"""
    if not isinstance(meeting_id, str) or not meeting_id.strip():
        return "meeting_id 必须是非空字符串"
    if not isinstance(utterances, list):
        return "utterances 必须是列表"
    bad = [i for i, u in enumerate(utterances) if not isinstance(u, Utterance)]
    if bad:
        return f"第 {bad[0]} 条发言不是 Utterance 对象"
    return None


def _student_metrics_from(gca) -> dict[str, dict[str, float]]:
    """GCAResult → {speaker_id: 六指标}。整节课和每个窗口共用。"""
    return {
        s: {
            "participation": gca.participation[s],
            "internal_cohesion": gca.internal_cohesion[s],
            "overall_responsivity": gca.overall_responsivity[s],
            "social_impact": gca.social_impact[s],
            "newness": gca.newness_by_speaker[s],
            "communication_density": gca.density_by_speaker[s],
        }
        for s in gca.speakers
    }


def analyze_utterances(
    meeting_id: str,
    utterances: list[Utterance],
    config: EngineConfig | None = None,
) -> GroupAnalysisResult:
    """对一次课堂讨论的发言做完整 GCA 分析（service 层调用本函数）。

    Args:
        meeting_id: 讨论小组 ID。
        utterances: 统一 Utterance 列表（schemas.py）。
        config:     可选 EngineConfig。

    Returns:
        GroupAnalysisResult（见 schemas.py）。
    """
    config = config or EngineConfig()

    error_msg = _validate(meeting_id, utterances)
    if error_msg is not None:
        return _error_result(meeting_id, AnalysisStatus.INVALID_INPUT, error_msg)

    n = len(utterances)
    if n == 0:
        return _error_result(
            meeting_id, AnalysisStatus.EMPTY_TRANSCRIPT, "没有任何发言记录"
        )

    # 按发言时间排序（引擎不假设输入已排序）
    ordered = sorted(utterances, key=lambda u: (u.timestamp, u.utterance_id))

    if n < config.min_utterances:
        return _error_result(
            meeting_id,
            AnalysisStatus.INSUFFICIENT_DATA,
            f"发言只有 {n} 条，少于最少 {config.min_utterances} 条",
        )

    texts = [u.text or "" for u in ordered]
    speaker_ids = [u.speaker_id for u in ordered]

    if config.tokenizer not in ("chinese", "legacy"):
        return _error_result(
            meeting_id,
            AnalysisStatus.INVALID_INPUT,
            f"未知的 tokenizer 配置：{config.tokenizer!r}（只支持 chinese / legacy）",
        )

    # --- 分词：LSA 和词数必须用同一套 token -------------------------------
    # chinese: 先走旧清洗（小写 + 去标点），再交给中文分词。LSA 吃的是
    #          "词之间用空格连起来"的文本，这样 TF-IDF 的 token_pattern=\S+
    #          统计的才是词，而不是整句。
    # legacy : 旧基线路径，LSA 直接吃原文，用于复现历史结果。
    if config.tokenizer == "legacy":
        tokens = [legacy_tokenize(t) for t in texts]
        lsa_texts = texts
    else:
        tokens = [chinese_tokenize(clean_text(t)) for t in texts]
        lsa_texts = [" ".join(ts) for ts in tokens]

    n_empty = sum(1 for ts in tokens if not ts)
    if n_empty == n:
        return _error_result(
            meeting_id,
            AnalysisStatus.INSUFFICIENT_DATA,
            "所有发言清洗后都为空文本，无法分析",
        )

    warnings: list[str] = []
    if n_empty > 0:
        warnings.append(f"有 {n_empty} 条发言清洗后为空文本，对应向量为零向量")

    # --- LSA 语义空间 ----------------------------------------------------
    try:
        model = fit_lsa_space(
            lsa_texts, config=LSAConfig(n_components=config.lsa_components)
        )
        vectors = project_texts(model, lsa_texts)
    except ValueError as e:
        return _error_result(
            meeting_id, AnalysisStatus.INSUFFICIENT_DATA,
            f"LSA 无法在本次发言上拟合：{e}",
        )
    if model.actual_dimensions != model.requested_dimensions:
        warnings.append(
            f"LSA 维度从 {model.requested_dimensions} 自动降到 "
            f"{model.actual_dimensions}（发言太少，属于正常现象）"
        )

    # --- GCA 六指标（数学与旧基线一致） ----------------------------------
    gca_config = GCAConfig()
    word_counts = [len(ts) for ts in tokens]
    gca = compute_gca_metrics(meeting_id, speaker_ids, vectors, word_counts, gca_config)

    student_metrics = _student_metrics_from(gca)

    if len(gca.speakers) == 1:
        warnings.append(
            "只有一名学生发言：overall_responsivity 和 social_impact 恒为 0"
        )
        status = AnalysisStatus.SINGLE_SPEAKER
    else:
        status = AnalysisStatus.SUCCESS

    duration = duration_seconds(ordered)

    # --- 时间窗口 ---------------------------------------------------------
    # 窗口内的指标必须在同一个语义空间里算，所以这里只切向量子集，
    # 不重新 fit_lsa_space（重新拟合会让每个窗口的坐标系都不一样）。
    timeline = None
    window_errors: list[dict] = []
    metadata_timeline: dict = {}
    if config.timeline_enabled:
        position = {id(u): i for i, u in enumerate(ordered)}

        def _analyze_subset(subset: list[Utterance]) -> dict[str, dict[str, float]]:
            """窗口子集 → 六指标。子集为空返回 {}，由 windows 记为无数据窗口。"""
            if not subset:
                return {}
            idx = [position[id(u)] for u in subset]
            sub_speakers = [speaker_ids[i] for i in idx]
            sub_vectors = vectors[idx]
            sub_counts = [word_counts[i] for i in idx]
            sub_gca = compute_gca_metrics(
                meeting_id, sub_speakers, sub_vectors, sub_counts, gca_config
            )
            return _student_metrics_from(sub_gca)

        timeline, window_warnings, window_errors = build_timeline(
            ordered,
            _analyze_subset,
            fixed_window_seconds=config.fixed_window_seconds,
            sliding_window_seconds=config.sliding_window_seconds,
            sliding_step_seconds=config.sliding_step_seconds,
            duration=duration,
        )
        warnings.extend(window_warnings)
        metadata_timeline = {
            "fixed_window_seconds": config.fixed_window_seconds,
            "sliding_window_seconds": config.sliding_window_seconds,
            "sliding_step_seconds": config.sliding_step_seconds,
            "n_fixed_windows": len(timeline["fixed_5min"]),
            "n_sliding_windows": len(timeline["sliding_5min"]),
        }
        if duration < config.fixed_window_seconds:
            warnings.append(
                f"课堂时长 {duration:g} 秒不足 {config.fixed_window_seconds // 60} 分钟，"
                "固定窗口只有一个"
            )
    else:
        warnings.append("timeline 已按 EngineConfig.timeline_enabled=False 关闭")

    metadata = {
        "n_utterances": n,
        "n_speakers": len(gca.speakers),
        "duration_seconds": float(duration),
        "empty_text_count": n_empty,
        "lsa": {
            "requested_dimensions": model.requested_dimensions,
            "actual_dimensions": model.actual_dimensions,
        },
        "tokenization": {
            "scheme": config.tokenizer,
            "total_tokens": int(sum(len(ts) for ts in tokens)),
            "tokens_per_utterance": float(sum(len(ts) for ts in tokens) / n),
        },
        "gca_config": gca_config.to_dict(),
        "timeline": metadata_timeline,
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if window_errors:
        # 失败窗口的具体原因只放在 metadata，避免 warnings 里刷一长串
        metadata["window_errors"] = window_errors

    return GroupAnalysisResult(
        meeting_id=meeting_id,
        status=status,
        student_metrics=student_metrics,
        group_metrics=group_metric_stats(student_metrics),
        timeline=timeline,
        metadata=metadata,
        warnings=warnings,
        error=None,
    )
