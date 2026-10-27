"""gca_service：主仓库数据 → GCA 六指标的接入层。"""

from datetime import timedelta
from uuid import uuid4

from app.core import database
from app.models import Meeting, Transcript
from app.services.gca_service import analyze_meeting_metrics
from fixtures import BASE_TIME
from gca_engine.schemas import SIX_METRICS


def _create_meeting(db, *, with_transcripts: bool = True):
    meeting = Meeting(
        class_code=f"GCA-{uuid4().hex[:8]}",
        teacher_id=1,
        topic="GCA 接入测试",
        knowledge_points=[],
        status="running",
        created_at=BASE_TIME,
        started_at=BASE_TIME,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    if with_transcripts:
        rows = [
            (2, "我认为我们应该先确定研究问题", 10),
            (3, "我同意，不过时间可能不够", 40),
            (2, "我们可以把任务拆成几个步骤", 70),
            (1, "老师补充一句", 100),
        ]
        for user_id, text, offset in rows:
            at = BASE_TIME + timedelta(seconds=offset)
            db.add(
                Transcript(
                    meeting_id=meeting.id,
                    user_id=user_id,
                    content=text,
                    timestamp=at,
                    created_at=at,
                )
            )
        db.commit()

    return meeting.id


def _cleanup(db, meeting_id: int) -> None:
    db.query(Transcript).filter(Transcript.meeting_id == meeting_id).delete()
    db.query(Meeting).filter(Meeting.id == meeting_id).delete()
    db.commit()


def test_metrics_exclude_teacher_and_use_six_metrics(seeded_ids):
    db = database.SessionLocal()
    meeting_id = _create_meeting(db)
    try:
        result = analyze_meeting_metrics(meeting_id, db)
    finally:
        _cleanup(db, meeting_id)
        db.close()

    assert result["status"] == "success"
    assert set(result["student_metrics"]) == {"2", "3"}
    assert set(result["group_metrics"]) == set(SIX_METRICS)
    assert result["timeline"] is not None


def test_empty_meeting_returns_empty_transcript(seeded_ids):
    db = database.SessionLocal()
    meeting_id = _create_meeting(db, with_transcripts=False)
    try:
        result = analyze_meeting_metrics(meeting_id, db)
    finally:
        _cleanup(db, meeting_id)
        db.close()

    assert result["status"] == "empty_transcript"
    assert result["student_metrics"] == {}


def test_missing_meeting_returns_not_found(seeded_ids):
    db = database.SessionLocal()
    try:
        result = analyze_meeting_metrics(999999, db)
    finally:
        db.close()

    assert result["status"] == "not_found"
