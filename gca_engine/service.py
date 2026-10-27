"""
gca_engine.service —— 对外统一入口（负责人：葛艾蓝）。

Agent 组 / 课堂系统只调用一个函数：

    from gca_engine import analyze_group
    result = analyze_group(meeting_id)

v0.1 数据来源：register_meeting() 注册的内存登记表。
以后接入真实课堂数据时，把这里的存储换成正式数据源即可，
analyze_group 的签名和返回格式保持不变。
"""

import logging
from dataclasses import replace

from gca_engine.engine import analyze_utterances
from gca_engine.schemas import AnalysisStatus, GroupAnalysisResult, Utterance

logger = logging.getLogger(__name__)

# v0.1 临时存储：meeting_id -> 该小组的发言列表
_MEETING_STORE: dict[str, list[Utterance]] = {}


def register_meeting(meeting_id: str, utterances: list[Utterance]) -> None:
    """注册一次课堂讨论的发言列表（v0.1 临时存储，之后换成正式数据源）。

    Raises:
        ValueError: 参数不合法，或发言的 meeting_id 与注册 ID 不一致。
    """
    if not isinstance(meeting_id, str) or not meeting_id.strip():
        raise ValueError("meeting_id 必须是非空字符串")
    if not isinstance(utterances, list) or not all(
        isinstance(u, Utterance) for u in utterances
    ):
        raise ValueError("utterances 必须是 Utterance 列表")
    if any(u.meeting_id != meeting_id for u in utterances):
        raise ValueError("每条发言的 meeting_id 必须与注册的 meeting_id 一致")

    # Utterance 可变：重新构造既复核当前字段，也隔离调用方后续的原地修改。
    # 全部记录通过校验后才替换登记，失败时保留原有数据。
    snapshot = [replace(u) for u in utterances]
    _MEETING_STORE[meeting_id] = snapshot


def clear_meeting(meeting_id: str) -> None:
    """从登记表里移除一个 meeting（不存在时不报错）。"""
    _MEETING_STORE.pop(meeting_id, None)


def list_meetings() -> list[str]:
    """当前已注册的 meeting_id 列表（按字母序）。"""
    return sorted(_MEETING_STORE)


def analyze_group(meeting_id: str) -> GroupAnalysisResult:
    """分析一个讨论小组（Agent 组统一调用入口）。

    Args:
        meeting_id: 讨论小组 ID（字符串）。

    Returns:
        GroupAnalysisResult（格式见 schemas.py）：
            meeting_id / status / student_metrics / group_metrics /
            timeline / metadata / warnings / error
        status 取值只有 AnalysisStatus 里的 7 种。
    """
    if not isinstance(meeting_id, str) or not meeting_id.strip():
        return GroupAnalysisResult(
            meeting_id=str(meeting_id),
            status=AnalysisStatus.INVALID_INPUT,
            student_metrics={},
            group_metrics={},
            timeline=None,
            metadata={},
            warnings=[],
            error="meeting_id 必须是非空字符串",
        )

    utterances = _MEETING_STORE.get(meeting_id)
    if utterances is None:
        return GroupAnalysisResult(
            meeting_id=meeting_id,
            status=AnalysisStatus.NOT_FOUND,
            student_metrics={},
            group_metrics={},
            timeline=None,
            metadata={},
            warnings=[],
            error=f"找不到 meeting_id={meeting_id!r}，请先用 register_meeting() 注册",
        )

    try:
        # 每次计算使用独立副本，防止引擎意外修改登记数据影响下一次分析。
        snapshot = [replace(u) for u in utterances]
        return analyze_utterances(meeting_id, snapshot)
    except Exception as e:  # 任何未预期错误都转成 internal_error，不让调用方崩溃
        logger.exception("analyze_group(%s) failed", meeting_id)
        return GroupAnalysisResult(
            meeting_id=meeting_id,
            status=AnalysisStatus.INTERNAL_ERROR,
            student_metrics={},
            group_metrics={},
            timeline=None,
            metadata={},
            warnings=[],
            error=f"{type(e).__name__}: {e}",
        )
