"""
gca_engine.engagement —— 第二阶段三维学习投入 + Hint 触发候选（GCA 组新增子包）。

本包当前包含（feat/gca，2026-11-20 更新）：

- protocols.py：公共数据结构（EmotionRecord / SpeechQualityRecord /
  EngagementDimensionResult / EngagementResult / HintCandidate），
  三维模块与整合层统一遵守；契约版本 ENGAGEMENT_PROTOCOL_VERSION。
- triggers.py：两类 Hint 触发候选（low_participation / discussion_stall），
  纯 Python 计算，不调 LLM。
- emotional.py：情感维度模块（岳柔），入口 analyze_emotional()
  （PR #26 已合入；timeline 窗口条目比引擎形状多一个可选的
  student_metrics 键，见 docs/engagement_protocol.md）。
- cognitive.py：认知维度模块（葛艾蓝），入口 analyze_cognitive()
  （PR #31 已合入）。
- behavioral.py：行为维度模块（雷梦琪），入口 analyze_behavioral()
  （PR #85 已合入；复用 windows.py 窗口边界与 aggregation 同口径汇总）。
- integration.py：三维统一整合入口 analyze_engagement()（组长），
  一次调用三个维度模块并投影出 EngagementResult，不重复计算指标。

维度模块按模块路径导入（如 gca_engine.engagement.emotional），
本包顶层只重导出协议、Hint 触发与整合入口相关的公共符号。
"""

from gca_engine.engagement.integration import analyze_engagement
from gca_engine.engagement.protocols import (
    DIMENSION_STATUS,
    DIMENSIONS,
    ENGAGEMENT_PROTOCOL_VERSION,
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
    "ENGAGEMENT_PROTOCOL_VERSION",
    "HINT_TYPES",
    "TARGET_TYPES",
    "EmotionRecord",
    "EngagementDimensionResult",
    "EngagementResult",
    "HintCandidate",
    "SpeechQualityRecord",
    "dimension_result",
    "HintTriggerConfig",
    "HintTriggerState",
    "compute_hint_candidates",
    "discussion_stall_candidates",
    "low_participation_candidates",
    "analyze_engagement",
]
