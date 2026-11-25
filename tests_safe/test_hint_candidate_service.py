"""Hint 候选评估：在线映射、冷却与课堂状态。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fixtures import BASE_TIME

from app.models import Meeting, Transcript, User
from app.realtime.registry import manager
from app.services.hint_candidate_service import (
    evaluate_hint_candidates,
    online_member_ids,
    reset_hint_state,
)


@pytest.fixture
def hint_meeting(seeded_ids):
    from app.core import database

    db = database.SessionLocal()
    try:
        quiet = User(
            student_id="S-QUIET-1",
            username="安静同学",
            password="not-a-real-hash",
            role="student",
        )
        db.add(quiet)
        db.commit()
        db.refresh(quiet)

        meeting = Meeting(
            class_code="HINT-SVC-1",
            teacher_id=seeded_ids["teacher_id"],
            topic="Hint 候选测试",
            status="running",
            knowledge_points=[],
            created_at=BASE_TIME,
            started_at=BASE_TIME,
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)

        for user_id, offsets in (
            (seeded_ids["student_id"], (10, 70, 130, 190, 230)),
            (seeded_ids["student_id_b"], (20, 80, 140, 200, 240)),
        ):
            for offset in offsets:
                db.add(
                    Transcript(
                        meeting_id=meeting.id,
                        user_id=user_id,
                        content="有效发言",
                        created_at=BASE_TIME + timedelta(seconds=offset),
                        timestamp=BASE_TIME + timedelta(seconds=offset),
                    )
                )
        db.commit()

        users = (
            db.query(User)
            .filter(
                User.id.in_(
                    [
                        seeded_ids["teacher_id"],
                        seeded_ids["student_id"],
                        seeded_ids["student_id_b"],
                        quiet.id,
                    ]
                )
            )
            .all()
        )
        manager.meeting_connections[meeting.id] = {user.username: object() for user in users}

        yield meeting, quiet

        manager.meeting_connections.pop(meeting.id, None)
        reset_hint_state(meeting.id)
        db.query(Transcript).filter(Transcript.meeting_id == meeting.id).delete()
        db.query(Meeting).filter(Meeting.id == meeting.id).delete()
        db.query(User).filter(User.id == quiet.id).delete()
        db.commit()
    finally:
        db.close()


def test_online_members_exclude_teacher_and_map_ids(hint_meeting, seeded_ids):
    from app.core import database

    meeting, quiet = hint_meeting
    db = database.SessionLocal()
    try:
        ids = online_member_ids(meeting.id, db)
    finally:
        db.close()

    assert set(ids) == {
        str(seeded_ids["student_id"]),
        str(seeded_ids["student_id_b"]),
        str(quiet.id),
    }
    assert str(seeded_ids["teacher_id"]) not in ids


def test_evaluate_produces_low_participation_and_cools_down(hint_meeting):
    from app.core import database

    meeting, quiet = hint_meeting
    db = database.SessionLocal()
    try:
        first = evaluate_hint_candidates(meeting.id, db, now_second=240)
        second = evaluate_hint_candidates(meeting.id, db, now_second=240)
    finally:
        db.close()

    assert first["status"] == "success"
    low = [item for item in first["candidates"] if item["hint_type"] == "low_participation"]
    assert low
    assert low[0]["target_user_id"] == str(quiet.id)
    assert first["online_member_count"] == 3
    assert second["candidate_count"] == 0


def test_reset_state_allows_new_candidate(hint_meeting):
    from app.core import database

    meeting, _quiet = hint_meeting
    db = database.SessionLocal()
    try:
        evaluate_hint_candidates(meeting.id, db, now_second=240)
        reset_hint_state(meeting.id)
        again = evaluate_hint_candidates(meeting.id, db, now_second=241)
    finally:
        db.close()

    assert any(item["hint_type"] == "low_participation" for item in again["candidates"])


def test_non_running_meeting_returns_no_candidates(hint_meeting):
    from app.core import database

    meeting, _quiet = hint_meeting
    db = database.SessionLocal()
    try:
        row = db.query(Meeting).filter(Meeting.id == meeting.id).first()
        row.status = "ended"
        db.commit()
        result = evaluate_hint_candidates(meeting.id, db)
    finally:
        db.close()

    assert result["status"] == "not_running"
    assert result["candidates"] == []
