"""课堂 GCA 六指标接入层（只读）。

把主仓库的 Transcript 数据转换成 gca_engine 的统一输入，再调用引擎的
无状态入口 `analyze_utterances()`。不使用引擎自带的进程内登记表。
"""

from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Meeting, Transcript, User
from app.services.collaboration_signal_service import build_collaboration_signals
from app.services.student_collaboration_feedback_service import (
    build_student_collaboration_feedback,
)
from app.services.transcript_query_service import TranscriptQueryService
from gca_engine.adapters.classroom import transcripts_to_utterances
from gca_engine.engine import analyze_utterances
from gca_engine.schemas import AnalysisStatus


def _not_found(meeting_id: int) -> Dict[str, Any]:
    return {
        "meeting_id": str(meeting_id),
        "status": AnalysisStatus.NOT_FOUND.value,
        "student_metrics": {},
        "group_metrics": {},
        "timeline": None,
        "metadata": {},
        "warnings": [],
        "error": "课堂不存在",
    }


def analyze_meeting_metrics(meeting_id: int, db: Session) -> Dict[str, Any]:
    """分析一节课的 GCA 六指标（质量层）。

    教师发言会被排除；时间戳统一转换为以课堂开始为零点的秒数。
    数据不足时返回引擎的状态，不抛异常。
    """
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if meeting is None:
        return _not_found(meeting_id)

    transcripts = [
        item
        for item in TranscriptQueryService(db).list_for_meeting(meeting_id)
        if getattr(item.user, "role", None) != "teacher"
    ]

    times = [item.created_at or item.timestamp for item in transcripts]
    times = [value for value in times if value is not None]
    origin = meeting.started_at or (min(times) if times else None)

    records = []
    for item in transcripts:
        occurred_at = item.created_at or item.timestamp
        if occurred_at is None or origin is None:
            continue
        records.append(
            {
                "id": item.id,
                "user_id": item.user_id,
                "content": item.content or "",
                "timestamp": max(0.0, (occurred_at - origin).total_seconds()),
            }
        )

    utterances = transcripts_to_utterances(records, meeting_id)
    return analyze_utterances(str(meeting_id), utterances).to_dict()


def build_gca_dashboard(meeting_id: int, db: Session) -> Dict[str, Any]:
    """Compose a teacher-dashboard payload without changing the engine contract."""
    result = analyze_meeting_metrics(meeting_id, db)
    student_metrics = result.get("student_metrics") or {}

    student_ids: list[int] = []
    for raw_id in student_metrics:
        try:
            student_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue

    users = (
        db.query(User)
        .filter(User.id.in_(student_ids), User.role != "teacher")
        .all()
        if student_ids
        else []
    )
    users_by_id = {str(user.id): user for user in users}

    count_rows = (
        db.query(Transcript.user_id, func.count(Transcript.id))
        .join(User, User.id == Transcript.user_id)
        .filter(
            Transcript.meeting_id == meeting_id,
            User.role != "teacher",
        )
        .group_by(Transcript.user_id)
        .all()
    )
    utterance_counts = {str(user_id): int(count) for user_id, count in count_rows}

    students = []
    for student_id, metrics in student_metrics.items():
        key = str(student_id)
        user = users_by_id.get(key)
        students.append(
            {
                "id": key,
                "name": getattr(user, "username", None) or f"学生 {key}",
                "student_id": getattr(user, "student_id", None),
                "utterance_count": utterance_counts.get(key, 0),
                "metrics": metrics,
            }
        )
    students.sort(key=lambda item: (-item["utterance_count"], item["name"]))

    metadata = result.get("metadata") or {}
    return {
        "status": result.get("status"),
        "meeting_id": meeting_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": {
            "student_count": int(metadata.get("n_speakers") or len(students)),
            "utterance_count": int(metadata.get("n_utterances") or 0),
            "duration_seconds": float(metadata.get("duration_seconds") or 0.0),
        },
        "group_metrics": result.get("group_metrics") or {},
        "students": students,
        "timeline": result.get("timeline"),
        "signals": build_collaboration_signals(result),
        "warnings": result.get("warnings") or [],
        "error": result.get("error"),
        "metadata": metadata,
    }


def _class_average(group_metrics: Dict[str, Any]) -> Dict[str, float]:
    """Expose only anonymous means; min/max can reveal classmates in small groups."""
    averages: Dict[str, float] = {}
    for metric, stats in (group_metrics or {}).items():
        value = (stats or {}).get("mean")
        if isinstance(value, (int, float)):
            averages[str(metric)] = float(value)
    return averages


def _anonymous_timeline(timeline: Dict[str, Any] | None) -> Dict[str, Any] | None:
    """Keep group aggregates and time bounds, never individual speaker data."""
    if not isinstance(timeline, dict):
        return None
    sanitized: Dict[str, list[Dict[str, Any]]] = {}
    for timeline_type in ("fixed_5min", "sliding_5min"):
        windows = []
        for raw in timeline.get(timeline_type) or []:
            if not isinstance(raw, dict):
                continue
            item = {
                key: raw.get(key)
                for key in ("start_second", "end_second", "center_second")
                if key in raw
            }
            item["group_metrics"] = {
                str(metric): {"mean": float(stats["mean"])}
                for metric, stats in (raw.get("group_metrics") or {}).items()
                if isinstance(stats, dict) and isinstance(stats.get("mean"), (int, float))
            }
            windows.append(item)
        sanitized[timeline_type] = windows
    return sanitized


def build_gca_student_view(
    meeting_id: int, student: User, db: Session
) -> Dict[str, Any]:
    """Build a privacy-filtered GCA view for one student."""
    result = analyze_meeting_metrics(meeting_id, db)
    student_key = str(student.id)
    metrics = (result.get("student_metrics") or {}).get(student_key) or {}
    group_metrics = result.get("group_metrics") or {}
    class_average = _class_average(group_metrics)

    own_utterance_count = int(
        db.query(func.count(Transcript.id))
        .filter(
            Transcript.meeting_id == meeting_id,
            Transcript.user_id == student.id,
        )
        .scalar()
        or 0
    )
    metadata = result.get("metadata") or {}
    total_utterance_count = int(metadata.get("n_utterances") or 0)
    status = str(result.get("status") or AnalysisStatus.INTERNAL_ERROR.value)

    return {
        "status": status,
        "meeting_id": meeting_id,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": {
            "own_utterance_count": own_utterance_count,
            "total_utterance_count": total_utterance_count,
            "student_count": int(metadata.get("n_speakers") or 0),
            "duration_seconds": float(metadata.get("duration_seconds") or 0.0),
        },
        "student": {
            "id": student_key,
            "name": student.username,
            "student_id": student.student_id,
            "metrics": metrics,
        },
        "class_average": class_average,
        "timeline": _anonymous_timeline(result.get("timeline")),
        "suggestions": build_student_collaboration_feedback(
            status=status,
            student_metrics=metrics,
            class_average=class_average,
            own_utterance_count=own_utterance_count,
            total_utterance_count=total_utterance_count,
        ),
        "warnings": result.get("warnings") or [],
        "error": result.get("error"),
    }
