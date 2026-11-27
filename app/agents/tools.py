"""Classroom Group Analysis Agent 的课堂级工具。"""

import logging
from dataclasses import dataclass
from typing import Any

from agents import RunContextWrapper, function_tool
from sqlalchemy.orm import Session

from app.agents.state import require_tool_state
from app.services.classroom_agent_service import classroom_agent_service

logger = logging.getLogger(__name__)


def tool_failure_message(ctx: RunContextWrapper[Any], error: Exception) -> str:
    """工具异常回传给模型，同时把堆栈写进服务端日志。"""
    logger.exception("agent tool failed: %s", error)
    return f"工具执行失败：{type(error).__name__}: {error}"


def _tool(func):
    return function_tool(func, failure_error_function=tool_failure_message)


@dataclass
class ClassroomToolContext:
    db: Session


@_tool
def get_classroom_transcripts(
    ctx: RunContextWrapper[ClassroomToolContext],
    meeting_id: int,
    limit: int = 200,
) -> dict[str, Any]:
    """读取课堂学生发言，返回带 T# 编号的原始证据。"""
    if denied := require_tool_state("get_classroom_transcripts", ctx.context.db, meeting_id):
        return denied
    return classroom_agent_service.get_transcripts(ctx.context.db, meeting_id, limit)


@_tool
def get_classroom_statistics(
    ctx: RunContextWrapper[ClassroomToolContext],
    meeting_id: int,
) -> dict[str, Any]:
    """读取课堂发言、互动、质量和情绪统计。"""
    if denied := require_tool_state("get_classroom_statistics", ctx.context.db, meeting_id):
        return denied
    return classroom_agent_service.get_statistics(ctx.context.db, meeting_id)


@_tool
def get_classroom_knowledge(
    ctx: RunContextWrapper[ClassroomToolContext],
    meeting_id: int,
) -> dict[str, Any]:
    """读取课堂知识图谱及学习目标覆盖情况。"""
    if denied := require_tool_state("get_classroom_knowledge", ctx.context.db, meeting_id):
        return denied
    return classroom_agent_service.get_knowledge(ctx.context.db, meeting_id)


@_tool
def get_class_metrics(
    ctx: RunContextWrapper[ClassroomToolContext],
    meeting_id: int,
) -> dict[str, Any]:
    """读取课堂 GCA 六指标（质量层）与时间窗口趋势。"""
    if denied := require_tool_state("get_class_metrics", ctx.context.db, meeting_id):
        return denied
    return classroom_agent_service.get_metrics(ctx.context.db, meeting_id)


@_tool
def get_engagement(
    ctx: RunContextWrapper[ClassroomToolContext],
    meeting_id: int,
    dimension: str | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """读取已落库的三维投入曲线（按窗口）。"""
    if denied := require_tool_state("get_engagement", ctx.context.db, meeting_id):
        return denied
    return classroom_agent_service.get_engagement(ctx.context.db, meeting_id, dimension, user_id)


@_tool
def get_hint_history(
    ctx: RunContextWrapper[ClassroomToolContext],
    meeting_id: int,
    limit: int = 50,
) -> dict[str, Any]:
    """读取已发送的 Hint 记录，返回带 H# 编号的证据。"""
    if denied := require_tool_state("get_hint_history", ctx.context.db, meeting_id):
        return denied
    return classroom_agent_service.get_hint_history(ctx.context.db, meeting_id, limit)


CLASSROOM_TOOLS = (
    get_classroom_transcripts,
    get_classroom_statistics,
    get_classroom_knowledge,
    get_class_metrics,
    get_engagement,
    get_hint_history,
)
