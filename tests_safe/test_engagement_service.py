"""三维投入落库适配：组装、覆盖写入与幂等。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fixtures import BASE_TIME

from app.models import EmotionLog, EngagementCurve, Meeting, Transcript
from app.services.engagement_service import rebuild_engagement_curves


def _make_meeting(db, teacher_id: int, with_data: bool = True):
    meeting = Meeting(
        class_code="ENG-SVC-1",
        teacher_id=teacher_id,
        topic="投入落库测试",
        status="ended",
        knowledge_points=[],
        created_at=BASE_TIME,
        started_at=BASE_TIME,
        ended_at=BASE_TIME + timedelta(minutes=10),
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    if not with_data:
        return meeting

    for index, (user_id, text) in enumerate(
        [
            (2, "我认为光合作用需要光照"),
            (3, "还有二氧化碳和水"),
            (2, "产物是葡萄糖和氧气"),
            (3, "叶绿体是主要场所"),
        ]
    ):
        db.add(
            Transcript(
                meeting_id=meeting.id,
                user_id=user_id,
                content=text,
                quality_score=85,
                quality_feedback="已评估",
                created_at=BASE_TIME + timedelta(minutes=index + 1),
                timestamp=BASE_TIME + timedelta(minutes=index + 1),
            )
        )
    db.add(
        Transcript(
            meeting_id=meeting.id,
            user_id=1,
            content="老师的讲解不应进入投入分析",
            quality_score=90,
            quality_feedback="已评估",
            created_at=BASE_TIME + timedelta(minutes=2),
            timestamp=BASE_TIME + timedelta(minutes=2),
        )
    )
    db.add_all(
        [
            EmotionLog(
                meeting_id=meeting.id,
                user_id=2,
                emotion_type="开心",
                intensity=0.8,
                created_at=BASE_TIME + timedelta(minutes=1),
            ),
            EmotionLog(
                meeting_id=meeting.id,
                user_id=3,
                emotion_type="开心",
                intensity=0.7,
                created_at=BASE_TIME + timedelta(minutes=2),
            ),
        ]
    )
    db.commit()
    return meeting


@pytest.fixture
def meeting(seeded_ids):
    from app.core import database

    db = database.SessionLocal()
    try:
        row = _make_meeting(db, seeded_ids["teacher_id"])
        yield row
        db.query(EngagementCurve).filter(EngagementCurve.meeting_id == row.id).delete()
        db.query(EmotionLog).filter(EmotionLog.meeting_id == row.id).delete()
        db.query(Transcript).filter(Transcript.meeting_id == row.id).delete()
        db.query(Meeting).filter(Meeting.id == row.id).delete()
        db.commit()
    finally:
        db.close()


def test_rebuild_writes_group_and_student_rows(meeting):
    from app.core import database

    db = database.SessionLocal()
    try:
        result = rebuild_engagement_curves(meeting.id, db)
        rows = db.query(EngagementCurve).filter(EngagementCurve.meeting_id == meeting.id).all()
    finally:
        db.close()

    assert result["status"] == "success"
    assert result["analysis_status"] == "success"
    assert result["rows"] == len(rows) > 0
    assert result["protocol_version"] == "1.0"

    dimensions = {row.dimension for row in rows}
    assert dimensions == {"emotional", "behavioral", "cognitive"}

    group_rows = [row for row in rows if row.user_id is None]
    student_rows = [row for row in rows if row.user_id is not None]
    assert {row.dimension for row in group_rows} == dimensions
    assert {row.user_id for row in student_rows} == {2, 3}
    assert all(row.user_id != 1 for row in rows)
    assert all(row.protocol_version == "1.0" for row in rows)
    assert all(row.window_end_second >= row.window_start_second for row in rows)
    assert all(row.status in {"ok", "insufficient", "unavailable"} for row in rows)


def test_rebuild_is_idempotent(meeting):
    from app.core import database

    db = database.SessionLocal()
    try:
        first = rebuild_engagement_curves(meeting.id, db)
        first_count = (
            db.query(EngagementCurve).filter(EngagementCurve.meeting_id == meeting.id).count()
        )
        second = rebuild_engagement_curves(meeting.id, db)
        second_count = (
            db.query(EngagementCurve).filter(EngagementCurve.meeting_id == meeting.id).count()
        )
    finally:
        db.close()

    assert first["rows"] == second["rows"] == first_count == second_count


def test_missing_meeting_returns_not_found():
    from app.core import database

    db = database.SessionLocal()
    try:
        assert rebuild_engagement_curves(999999, db) == {
            "status": "not_found",
            "meeting_id": 999999,
        }
    finally:
        db.close()


def test_empty_meeting_writes_no_rows(seeded_ids):
    from app.core import database

    db = database.SessionLocal()
    try:
        row = _make_meeting(db, seeded_ids["teacher_id"], with_data=False)
        try:
            result = rebuild_engagement_curves(row.id, db)
            count = db.query(EngagementCurve).filter(EngagementCurve.meeting_id == row.id).count()
        finally:
            db.query(EngagementCurve).filter(EngagementCurve.meeting_id == row.id).delete()
            db.query(Meeting).filter(Meeting.id == row.id).delete()
            db.commit()
    finally:
        db.close()

    assert result["analysis_status"] == "insufficient_data"
    assert result["rows"] == count == 0
