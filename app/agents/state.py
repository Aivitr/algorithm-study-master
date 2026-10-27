"""课堂生命周期门禁。

状态直接读 `Meeting.status`（created / running / ended），不再用发言或连接
反推状态；状态机由 app.core.meeting_state 统一维护。
"""

from enum import StrEnum

from sqlalchemy.orm import Session

from app.models import Meeting


class ClassroomState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    ENDED = "ended"


READ_STATES = frozenset({ClassroomState.RUNNING, ClassroomState.ENDED})

# 只登记真实存在的工具；新增工具时同步这里，/tools 会据此返回允许状态。
TOOL_STATES = {
    "get_classroom_transcripts": READ_STATES,
    "get_classroom_statistics": READ_STATES,
    "get_classroom_knowledge": READ_STATES,
    "get_class_metrics": READ_STATES,
}


def resolve_classroom_state(db: Session, meeting_id: int) -> ClassroomState | None:
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        return None
    try:
        return ClassroomState(meeting.status)
    except ValueError:
        return None


def require_tool_state(tool_name: str, db: Session, meeting_id: int) -> dict | None:
    state = resolve_classroom_state(db, meeting_id)
    allowed_states = TOOL_STATES.get(tool_name, frozenset())
    if state is not None and state in allowed_states:
        return None

    allowed_tools = [
        name
        for name, states in TOOL_STATES.items()
        if state is not None and state in states and name != tool_name
    ]
    state_label = state.value if state is not None else "missing"
    reason = (
        f"当前课堂状态为 {state_label}，工具 {tool_name} 不可用"
        if state is not None
        else f"课堂不存在，工具 {tool_name} 不可用"
    )
    return {
        "ok": False,
        "allowed": False,
        "state": state_label,
        "reason": reason,
        "suggested_tools": allowed_tools,
    }
