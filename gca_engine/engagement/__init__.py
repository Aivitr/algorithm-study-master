"""
gca_engine.engagement —— 第二阶段三维学习投入 + Hint 触发候选（GCA 组新增子包）。

本包当前包含（2026-11-19 更新）：

- protocols.py：公共数据结构（EmotionRecord / SpeechQualityRecord /
  EngagementDimensionResult / EngagementResult / HintCandidate），
  三维模块与整合层统一遵守。
- triggers.py：两类 Hint 触发候选（low_participation / discussion_stall），
  纯 Python 计算，不调 LLM。
- emotional.py：情感维度模块（岳柔），入口 analyze_emotional()。
- behavioral.py：行为维度模块，入口 analyze_behavioral()
  （发言次数、参与比例、频率；未接入动作数据）。
- cognitive.py：认知维度模块（葛艾蓝），入口 analyze_cognitive()。
- integration.py：整合入口 analyze_engagement()，投影三个维度结果，
  不重复计算，也不输出综合分。

维度模块按模块路径导入（如 gca_engine.engagement.emotional），
本包顶层重导出协议、Hint 候选与整合入口。
"""

from gca_engine.engagement.behavioral import analyze_behavioral
from gca_engine.engagement.integration import PROTOCOL_VERSION, analyze_engagement
from gca_engine.engagement.protocols import (
    DIMENSION_STATUS,
    DIMENSIONS,
    HINT_TYPES,
    TARGET_TYPES,
    EmotionRecord,
    EngagementDimensionResult,
    EngagementResult,
    HintCandidate,
    SpeechQualityRecord,
    dimension_result,
)
from gca_engine.engagement.triggers import (
    HintTriggerConfig,
    HintTriggerState,
    compute_hint_candidates,
    discussion_stall_candidates,
    low_participation_candidates,
)

__all__ = [
    "DIMENSIONS",
    "DIMENSION_STATUS",
    "HINT_TYPES",
    "PROTOCOL_VERSION",
    "TARGET_TYPES",
    "EmotionRecord",
    "EngagementDimensionResult",
    "EngagementResult",
    "HintCandidate",
    "SpeechQualityRecord",
    "analyze_behavioral",
    "analyze_engagement",
    "dimension_result",
    "HintTriggerConfig",
    "HintTriggerState",
    "compute_hint_candidates",
    "discussion_stall_candidates",
    "low_participation_candidates",
]
