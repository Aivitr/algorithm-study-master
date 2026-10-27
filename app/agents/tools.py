"""Classroom Group Analysis Agent 的课堂级工具。"""

from dataclasses import dataclass
from typing import Any

from agents import RunContextWrapper, function_tool
from sqlalchemy.orm import Session

from app.agents.state import require_tool_state
from app.services.classroom_agent_service import classroom_agent_service


@dataclass
class ClassroomToolContext:
    db: Session


@function_tool
def get_classroom_transcripts(
    ctx: RunContextWrapper[ClassroomToolContext],
    meeting_id: int,
    limit: int = 200,
) -> dict[str, Any]:
    """读取课堂学生发言，返回带 T# 编号的原始证据。"""
    if denied := require_tool_state("get_classroom_transcripts", ctx.context.db, meeting_id):
        return denied
    return classroom_agent_service.get_transcripts(ctx.context.db, meeting_id, limit)


@function_tool
def get_classroom_statistics(
    ctx: RunContextWrapper[ClassroomToolContext],
    meeting_id: int,
) -> dict[str, Any]:
    """读取课堂发言、互动、质量和情绪统计。"""
    if denied := require_tool_state("get_classroom_statistics", ctx.context.db, meeting_id):
        return denied
    return classroom_agent_service.get_statistics(ctx.context.db, meeting_id)


@function_tool
def get_classroom_knowledge(
    ctx: RunContextWrapper[ClassroomToolContext],
    meeting_id: int,
) -> dict[str, Any]:
    """读取课堂知识图谱及学习目标覆盖情况。"""
    if denied := require_tool_state("get_classroom_knowledge", ctx.context.db, meeting_id):
        return denied
    return classroom_agent_service.get_knowledge(ctx.context.db, meeting_id)


@function_tool
def get_class_metrics(
    ctx: RunContextWrapper[ClassroomToolContext],
    meeting_id: int,
) -> dict[str, Any]:
    """读取课堂 GCA 六指标（质量层）与时间窗口趋势。"""
    if denied := require_tool_state("get_class_metrics", ctx.context.db, meeting_id):
        return denied
    return classroom_agent_service.get_metrics(ctx.context.db, meeting_id)


CLASSROOM_TOOLS = (
    get_classroom_transcripts,
    get_classroom_statistics,
    get_classroom_knowledge,
    get_class_metrics,
)
