"""
课堂小组讨论分析引擎 —— 后端算法组共同仓库。

统一入口（Agent 组 / 课堂系统只用这个）：

    from gca_engine import analyze_group
    result = analyze_group(meeting_id)

数据流：
    课堂发言 → adapters 转统一 Utterance → 中文预处理 + LSA
    → GCA 六指标 → 小组汇总 → 统一结果（schemas.GroupAnalysisResult）
"""

from gca_engine.service import (
    analyze_group,
    clear_meeting,
    list_meetings,
    register_meeting,
)

__version__ = "0.1.0"

__all__ = [
    "analyze_group",
    "register_meeting",
    "clear_meeting",
    "list_meetings",
    "__version__",
]
