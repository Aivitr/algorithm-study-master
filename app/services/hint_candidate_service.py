"""Hint 候选评估：在线成员映射、课堂相对时刻与候选级冷却。"""

from __future__ import annotations

from datetime import datetime, timedelta
from threading import Lock

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import HintLog, Meeting, User
from app.realtime.registry import manager
from app.services.engagement_service import build_utterances
from gca_engine.engagement import (
    HintTriggerConfig,
    HintTriggerState,
    compute_hint_candidates,
)

_HINT_CONFIG = HintTriggerConfig()

# 每个课堂一份候选冷却状态；进程内单 worker，重启会丢失（已写入契约）。
_states: dict[int, HintTriggerState] = {}
_states_lock = Lock()


def _state_for(meeting_id: int) -> HintTriggerState:
    with _states_lock:
        return _states.setdefault(meeting_id, HintTriggerState())


def reset_hint_state(meeting_id: int) -> None:
    """课堂结束后清理状态，避免内存长期累积。"""
    with _states_lock:
        _states.pop(meeting_id, None)


def record_sent_hint(
    db: Session,
    *,
    meeting_id: int,
    candidate: dict,
    text: str,
    created_by: int,
) -> None:
    """记录一次已发送的 Hint；写库失败只打日志，不影响课堂主流程。"""
    row = HintLog(
        meeting_id=meeting_id,
        dedupe_key=str(candidate.get("dedupe_key") or ""),
        hint_type=str(candidate.get("hint_type") or ""),
        target_type=str(candidate.get("target_type") or ""),
        target_user_id=candidate.get("target_user_id"),
        trigger_reason=candidate.get("trigger_reason"),
        evidence=candidate.get("evidence") or {},
        evidence_ids=[],
        text=text,
        model="llm",
        prompt_version="topic_suggestion_v1",
        status="sent",
        created_by=created_by,
        sent_at=datetime.now(),
    )
    db.add(row)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        print(f"[ERROR] Hint 记录写入失败: meeting_id={meeting_id}: {exc}")


def _send_cooldown_seconds(target_type: str) -> int:
    if target_type == "student":
        return _HINT_CONFIG.student_cooldown_seconds
    return _HINT_CONFIG.group_cooldown_seconds


def recently_sent(
    db: Session,
    meeting_id: int,
    dedupe_key: str,
    target_type: str,
) -> bool:
    """跨进程重启的发送级冷却：同一 dedupe_key 冷却期内不再发送。"""
    cutoff = datetime.now() - timedelta(seconds=_send_cooldown_seconds(target_type))
    return (
        db.query(HintLog.id)
        .filter(
            HintLog.meeting_id == meeting_id,
            HintLog.dedupe_key == dedupe_key,
            HintLog.sent_at >= cutoff,  # type: ignore[arg-type]
        )
        .first()
        is not None
    )


def filter_recent_sends(db: Session, meeting_id: int, candidates: list[dict]) -> list[dict]:
    return [
        candidate
        for candidate in candidates
        if not recently_sent(
            db,
            meeting_id,
            str(candidate.get("dedupe_key") or ""),
            str(candidate.get("target_type") or "group"),
        )
    ]


def online_member_ids(meeting_id: int, db: Session) -> list[str]:
    """把 WS 连接名映射成 User.id 字符串；教师排除，无学生在线时返回空列表。"""
    names = {str(name) for name in manager.get_online_members(meeting_id)}
    if not names:
        return []

    users = db.query(User).filter(or_(User.username.in_(names), User.student_id.in_(names))).all()
    return sorted({str(user.id) for user in users if user.role != "teacher"})


def _now_second(meeting: Meeting, last_utterance_second: float) -> float:
    if meeting.started_at is None:
        return last_utterance_second
    return max(0.0, (datetime.now() - meeting.started_at).total_seconds())


def evaluate_hint_candidates(
    meeting_id: int,
    db: Session,
    *,
    now_second: float | None = None,
) -> dict:
    """评估一次 Hint 候选；只产出候选，不调用 LLM、不发送消息。"""
    meeting, utterances = build_utterances(meeting_id, db)
    if meeting is None:
        return {"status": "not_found", "meeting_id": meeting_id, "candidates": []}
    if meeting.status != "running":
        return {"status": "not_running", "meeting_id": meeting_id, "candidates": []}

    points = [
        float(u.end_time) if u.end_time is not None else float(u.timestamp) for u in utterances
    ]
    last_second = max(points, default=0.0)
    now = float(now_second) if now_second is not None else _now_second(meeting, last_second)
    online = online_member_ids(meeting_id, db)
    candidates = compute_hint_candidates(
        str(meeting_id),
        utterances,
        now_second=now,
        state=_state_for(meeting_id),
        online_members=online,
    )

    return {
        "status": "success",
        "meeting_id": meeting_id,
        "now_second": now,
        "candidate_count": len(candidates),
        "online_member_count": len(online),
        "candidates": [candidate.to_dict() for candidate in candidates],
    }
