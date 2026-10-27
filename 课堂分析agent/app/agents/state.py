"""课堂生命周期门禁与状态 CAS。"""

from enum import StrEnum

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import Meeting, MemberConnection, Transcript


class ClassroomState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    ENDED = "ended"


READ_STATES = frozenset({ClassroomState.RUNNING, ClassroomState.ENDED})

TOOL_STATES = {
    "get_meeting_context": frozenset(ClassroomState),
    "get_classroom_transcripts": READ_STATES,
    "get_classroom_statistics": READ_STATES,
    "get_classroom_knowledge": READ_STATES,
    "discover_groups": READ_STATES,
    "get_group_evidence": READ_STATES,
    "compute_group_metrics": READ_STATES,
    "get_knowledge_trace": READ_STATES,
    "find_learning_gaps": READ_STATES,
    "simulate_intervention": READ_STATES,
    "dispatch_intervention": frozenset({ClassroomState.RUNNING}),
}


def resolve_classroom_state(db: Session, meeting_id: int) -> ClassroomState | None:
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        return None
    if meeting.status == "ended":
        return ClassroomState.ENDED
    if meeting.status == "paused":
        return ClassroomState.CREATED
    has_activity = db.query(Transcript.id).filter(
        Transcript.meeting_id == meeting_id
    ).first()
    has_member = db.query(MemberConnection.id).filter(
        MemberConnection.meeting_id == meeting_id
    ).first()
    return ClassroomState.RUNNING if has_activity or has_member else ClassroomState.CREATED


def require_tool_state(tool_name: str, db: Session, meeting_id: int) -> dict | None:
    state = resolve_classroom_state(db, meeting_id)
    allowed_states = TOOL_STATES.get(tool_name, frozenset())
    if state is not None and state in allowed_states:
        return None

    allowed_tools = [
        name
        for name, states in TOOL_STATES.items()
        if (state is None and name == "get_meeting_context")
        or (state is not None and state in states and name != tool_name)
    ]
    state_label = state.value if state is not None else "missing"
    return {
        "ok": False,
        "allowed": False,
        "state": state_label,
        "reason": f"当前课堂状态为 {state_label}，工具 {tool_name} 不可用",
        "suggested_tools": allowed_tools,
    }


def compare_and_set_meeting_status(
    db: Session,
    meeting_id: int,
    old_status: str,
    new_status: str,
) -> bool:
    if new_status not in {"active", "paused", "ended"}:
        raise ValueError(f"invalid meeting status: {new_status}")
    result = db.execute(
        update(Meeting)
        .where(Meeting.id == meeting_id, Meeting.status == old_status)
        .values(status=new_status)
    )
    return result.rowcount == 1
