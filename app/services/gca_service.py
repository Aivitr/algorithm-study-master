"""课堂 GCA 六指标接入层（只读）。

把主仓库的 Transcript 数据转换成 gca_engine 的统一输入，再调用引擎的
无状态入口 `analyze_utterances()`。不使用引擎自带的进程内登记表。
"""

from typing import Any, Dict

from sqlalchemy.orm import Session

from app.models import Meeting
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
