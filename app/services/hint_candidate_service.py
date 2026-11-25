"""Hint 候选评估、待发送队列与冷却。

- 评估：调用 GCA 的 `compute_hint_candidates`，只产出候选。
- 生成：为候选生成提示文案（LLM 失败走模板），写入 `hint_logs`（`status=candidate`）。
- 发送：由教师确认后触发（见 `app/routers/hints.py`），本模块不主动下发。
- 冷却：同一 `dedupe_key` 在冷却期内只生成一次；按 `created_at` 判定，跨重启生效。
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta
from threading import Lock
from typing import Any, cast

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import HintLog, Meeting, Transcript, User
from app.realtime.registry import manager
from app.services.engagement_service import build_utterances
from app.services.llm_service import llm
from app.services.observability_service import record_run
from gca_engine.engagement import (
    HintTriggerConfig,
    HintTriggerState,
    compute_hint_candidates,
)

PROMPT_VERSION = "topic_suggestion_v1"
AGENT_PROMPT_VERSION = "group_analysis_v1"
# 同一课堂 10 分钟内最多真正下发这么多条提示，避免刷屏。
SEND_RATE_WINDOW_SECONDS = 600
SEND_RATE_LIMIT = 5
# 未处理的候选上限，避免教师离开时收件箱无限堆积。
MAX_PENDING_HINTS = 10

_HINT_CONFIG = HintTriggerConfig()

# 每个课堂一份候选冷却状态；进程内单 worker，重启会丢失（冷却另由 hint_logs 兜底）。
_states: dict[int, HintTriggerState] = {}
_states_lock = Lock()


def _state_for(meeting_id: int) -> HintTriggerState:
    with _states_lock:
        return _states.setdefault(meeting_id, HintTriggerState())


def reset_hint_state(meeting_id: int) -> None:
    """课堂结束后清理状态，避免内存长期累积。"""
    with _states_lock:
        _states.pop(meeting_id, None)


def _send_cooldown_seconds(target_type: str) -> int:
    if target_type == "student":
        return _HINT_CONFIG.student_cooldown_seconds
    return _HINT_CONFIG.group_cooldown_seconds


def recent_hint_exists(
    db: Session,
    meeting_id: int,
    dedupe_key: str,
    target_type: str,
) -> bool:
    """冷却期内已有同键提示（候选或已发送）时不再生成。"""
    cutoff = datetime.now() - timedelta(seconds=_send_cooldown_seconds(target_type))
    return (
        db.query(HintLog.id)
        .filter(
            HintLog.meeting_id == meeting_id,
            HintLog.dedupe_key == dedupe_key,
            HintLog.created_at >= cutoff,  # type: ignore[arg-type]
        )
        .first()
        is not None
    )


def filter_duplicate_hints(db: Session, meeting_id: int, candidates: list[dict]) -> list[dict]:
    return [
        candidate
        for candidate in candidates
        if not recent_hint_exists(
            db,
            meeting_id,
            str(candidate.get("dedupe_key") or ""),
            str(candidate.get("target_type") or "group"),
        )
    ]


def create_pending_hint(
    db: Session,
    *,
    meeting_id: int,
    candidate: dict,
    text: str,
    created_by: int,
    model: str = "llm",
    prompt_version: str = PROMPT_VERSION,
    evidence_ids: list[str] | None = None,
) -> int | None:
    """写入一条待发送提示；写库失败只打日志，不影响课堂主流程。"""
    row = HintLog(
        meeting_id=meeting_id,
        dedupe_key=str(candidate.get("dedupe_key") or ""),
        hint_type=str(candidate.get("hint_type") or ""),
        target_type=str(candidate.get("target_type") or ""),
        target_user_id=candidate.get("target_user_id"),
        trigger_reason=candidate.get("trigger_reason"),
        evidence=candidate.get("evidence") or {},
        evidence_ids=evidence_ids or [],
        text=text,
        model=model,
        prompt_version=prompt_version,
        status="candidate",
        created_by=created_by,
        sent_at=None,
    )
    db.add(row)
    try:
        db.commit()
        return int(row.id)
    except Exception as exc:
        db.rollback()
        print(f"[ERROR] Hint 候选写入失败: meeting_id={meeting_id}: {exc}")
        return None


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


def _recent_context(db: Session, meeting_id: int) -> str:
    recents = (
        db.query(Transcript)
        .filter(Transcript.meeting_id == meeting_id)
        .order_by(Transcript.id.desc())
        .limit(5)
        .all()
    )
    return "\n".join([f"{t.user.username}: {t.content}" for t in reversed(recents)])


def _template_suggestion(topic: str, target_type: str) -> str:
    if target_type == "quiet":
        return f"可以请这位同学围绕「{topic}」补充一个例子或提出一个问题。"
    return f"课堂暂时安静，可以围绕「{topic}」提出一个具体问题，邀请学生回应。"


def _generate_suggestion(
    meeting: Meeting,
    discussion_context: str,
    target_type: str,
    hint_context: str,
) -> tuple[str, str, dict, int, str | None]:
    """生成提示文案并返回 (文案, 来源, token 用量, 耗时毫秒, 错误)。"""
    started = time.perf_counter()
    usage: dict = {}
    error = None
    hint_model = "llm"
    topic = cast(str, meeting.topic)
    goals = cast("list[Any]", meeting.knowledge_points)
    try:
        suggestion, usage = llm.generate_topic_suggestion_with_usage(
            topic,
            discussion_context,
            goals,
            target_type=target_type,
            hint_context=hint_context,
        )
    except Exception as exc:
        print(f"[WARN] 生成话题建议失败，使用模板: {exc}")
        suggestion = _template_suggestion(topic, target_type)
        hint_model = "template"
        error = str(exc)
    if not (suggestion or "").strip():
        suggestion = _template_suggestion(topic, target_type)
        hint_model = "template"
        error = error or "empty response"
    latency_ms = int((time.perf_counter() - started) * 1000)
    return suggestion, hint_model, usage, latency_ms, error


def generate_pending_hints(
    db: Session, meeting_id: int, *, kinds: set[str] | None = None
) -> list[dict]:
    """评估并生成待教师确认的提示；不发送。"""
    evaluation = evaluate_hint_candidates(meeting_id, db)
    if evaluation["status"] != "success":
        return []
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        return []

    candidates = [
        item for item in evaluation["candidates"] if kinds is None or item["hint_type"] in kinds
    ]
    candidates = filter_duplicate_hints(db, meeting_id, candidates)
    if not candidates:
        return []
    pending_count = (
        db.query(HintLog.id)
        .filter(HintLog.meeting_id == meeting_id, HintLog.status == "candidate")
        .count()
    )
    if pending_count >= MAX_PENDING_HINTS:
        return []

    base_ids = [f"T#{t.id}" for t in _recent_transcripts(db, meeting_id)]
    base_ids.append(f"M:{meeting_id}")

    discussion_context = _recent_context(db, meeting_id)
    pending: list[dict] = []
    latency_total = 0
    prompt_tokens = 0
    completion_tokens = 0
    model = "llm"
    error: str | None = None

    for candidate in candidates:
        hint_context = f"触发原因：{candidate['trigger_reason']}\n证据：{candidate['evidence']}"
        target_type = "quiet" if candidate["target_type"] == "student" else "group"
        text, model, usage, latency_ms, call_error = _generate_suggestion(
            meeting, discussion_context, target_type, hint_context
        )
        latency_total += latency_ms
        prompt_tokens += int(usage.get("prompt_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or 0)
        error = error or call_error
        hint_id = create_pending_hint(
            db,
            meeting_id=meeting_id,
            candidate=candidate,
            text=text,
            created_by=int(meeting.teacher_id),
            model=model,
            evidence_ids=base_ids,
        )
        if hint_id is None:
            continue
        pending.append({"hint_id": hint_id, **candidate, "text": text})

    record_run(
        db,
        meeting_id=meeting_id,
        kind="hint_llm",
        source=model,
        status="success" if model == "llm" else "fallback",
        model="deepseek-chat" if model == "llm" else "template",
        version=PROMPT_VERSION,
        latency_ms=latency_total,
        prompt_tokens=prompt_tokens or None,
        completion_tokens=completion_tokens or None,
        result={"pending": len(pending)},
        error=error,
    )
    return pending


def _recent_transcripts(db: Session, meeting_id: int, limit: int = 5) -> list[Transcript]:
    return (
        db.query(Transcript)
        .filter(Transcript.meeting_id == meeting_id)
        .order_by(Transcript.id.desc())
        .limit(limit)
        .all()
    )


def count_sent_recent(db: Session, meeting_id: int) -> int:
    cutoff = datetime.now() - timedelta(seconds=SEND_RATE_WINDOW_SECONDS)
    return (
        db.query(HintLog.id)
        .filter(
            HintLog.meeting_id == meeting_id,
            HintLog.status == "sent",
            HintLog.sent_at >= cutoff,  # type: ignore[arg-type]
        )
        .count()
    )


def store_agent_hints(
    db: Session,
    meeting_id: int,
    recommendations: list,
    created_by: int,
) -> int:
    """把 Agent 的 Hint 建议存入待发送队列；返回新建条数。"""
    created = 0
    for item in recommendations or []:
        text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        hint_type = (getattr(item, "hint_type", "") or "").strip() or "agent_suggestion"
        target = (getattr(item, "target", "") or "").strip()
        user = None
        if target:
            user = (
                db.query(User)
                .join(Transcript, Transcript.user_id == User.id)
                .filter(
                    Transcript.meeting_id == meeting_id,
                    User.username == target,
                    User.role == "student",
                )
                .first()
            )
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
        dedupe_key = f"agent:{meeting_id}:{hint_type}:{target}:{digest}"
        if recent_hint_exists(db, meeting_id, dedupe_key, "student" if user else "group"):
            continue
        candidate: dict[str, Any] = {
            "dedupe_key": dedupe_key,
            "hint_type": hint_type,
            "target_type": "student" if user else "group",
            "target_user_id": str(user.id) if user else None,
            "trigger_reason": (getattr(item, "reason", "") or "").strip(),
            "evidence": {},
        }
        hint_id = create_pending_hint(
            db,
            meeting_id=meeting_id,
            candidate=candidate,
            text=text,
            created_by=created_by,
            model="agent",
            prompt_version=AGENT_PROMPT_VERSION,
            evidence_ids=list(getattr(item, "evidence", []) or []),
        )
        if hint_id is not None:
            created += 1
    return created
