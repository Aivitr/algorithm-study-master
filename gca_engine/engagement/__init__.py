"""
gca_engine.engagement —— 第二阶段三维学习投入 + Hint 触发候选（GCA 组新增子包）。

本包当前包含（feat/gca，2026-11-14）：

- protocols.py：公共数据结构（EmotionRecord / SpeechQualityRecord /
  EngagementDimensionResult / EngagementResult / HintCandidate），
  三维模块与整合层统一遵守。
- triggers.py：两类 Hint 触发候选（low_participation / discussion_stall），
  纯 Python 计算，不调 LLM。

尚未实现（按分工进行中，不在本包占位）：

- emotional.py / behavioral.py / cognitive.py：三位组员各自的维度模块，
  函数签名见 docs/engagement_protocol.md 第 4 节。
- 整合入口 analyze_engagement(meeting_id, ...) -> EngagementResult：
  由组长实现，等三个维度模块合入后编写（投影三个维度结果，不重复计算）。
"""

from gca_engine.engagement.protocols import (
    DIMENSIONS,
    DIMENSION_STATUS,
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
]
