"""课堂 created -> running -> ended 生命周期及接口幂等性测试。

测试只使用隔离的本地 SQLite 与内存广播桩，不连接真实课堂或外部服务。
"""

from uuid import uuid4

import pytest


@pytest.fixture
def lifecycle_meeting(local_app, seeded_ids):
    from app.core.database import SessionLocal
    from app.models import Meeting

    db = SessionLocal()
    meeting = Meeting(
        class_code=f"LIFE-{uuid4().hex[:10]}",
        teacher_id=seeded_ids["teacher_id"],
        topic="课堂生命周期测试",
        knowledge_points=[],
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    meeting_id = meeting.id
    db.close()

    try:
        yield meeting_id
    finally:
        cleanup = SessionLocal()
        try:
            cleanup.query(Meeting).filter(Meeting.id == meeting_id).delete()
            cleanup.commit()
        finally:
            cleanup.close()


@pytest.fixture
def lifecycle_broadcasts(monkeypatch):
    import app.routers.classroom_ops as classroom_ops

    broadcasts = []

    async def fake_broadcast(meeting_id, payload):
        broadcasts.append((meeting_id, payload))

    monkeypatch.setattr(classroom_ops.manager, "broadcast_to_meeting", fake_broadcast)
    return broadcasts


def _start(client, meeting_id):
    return client.post(
        "/api/start-class",
        data={"meeting_id": meeting_id, "username": "T2026001"},
    )


def _end(client, meeting_id):
    return client.post(
        "/api/end-class",
        data={"meeting_id": meeting_id, "username": "T2026001"},
    )


def test_new_meeting_defaults_to_created(lifecycle_meeting):
    from app.core.database import SessionLocal
    from app.models import Meeting

    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == lifecycle_meeting).one()
        assert meeting.status == "created"
        assert meeting.started_at is None
        assert meeting.ended_at is None
    finally:
        db.close()


def test_start_class_is_idempotent(client, lifecycle_meeting):
    from app.core.database import SessionLocal
    from app.models import Meeting

    first = _start(client, lifecycle_meeting)
    assert first.status_code == 200
    assert first.json()["status"] == "success"
    assert first.json()["already_started"] is False
    assert first.json()["meeting_status"] == "running"

    db = SessionLocal()
    try:
        first_started_at = (
            db.query(Meeting).filter(Meeting.id == lifecycle_meeting).one().started_at
        )
    finally:
        db.close()
    assert first_started_at is not None

    second = _start(client, lifecycle_meeting)
    assert second.status_code == 200
    assert second.json()["status"] == "success"
    assert second.json()["already_started"] is True

    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == lifecycle_meeting).one()
        assert meeting.status == "running"
        assert meeting.started_at == first_started_at
    finally:
        db.close()


def test_atomic_start_claim_can_only_succeed_once(lifecycle_meeting):
    from datetime import datetime

    from app.core.database import SessionLocal
    from app.services.meeting_lifecycle import claim_start

    first_db = SessionLocal()
    second_db = SessionLocal()
    try:
        assert claim_start(first_db, lifecycle_meeting, datetime.now()) is True
        assert claim_start(second_db, lifecycle_meeting, datetime.now()) is False
    finally:
        first_db.close()
        second_db.close()


def test_end_before_start_is_rejected(client, lifecycle_meeting, lifecycle_broadcasts):
    response = _end(client, lifecycle_meeting)
    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert "尚未开始" in response.json()["message"]
    assert lifecycle_broadcasts == []


def test_other_teacher_cannot_start_class(client, lifecycle_meeting):
    from app.core.database import SessionLocal
    from app.models import User

    other_student_id = f"T-{uuid4().hex[:10]}"
    db = SessionLocal()
    other = User(
        student_id=other_student_id,
        username="其他教师",
        password="not-a-real-hash",
        role="teacher",
    )
    db.add(other)
    db.commit()
    other_id = other.id
    db.close()

    try:
        response = client.post(
            "/api/start-class",
            data={"meeting_id": lifecycle_meeting, "username": other_student_id},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "error"
        assert "本课堂教师" in response.json()["message"]
    finally:
        cleanup = SessionLocal()
        try:
            cleanup.query(User).filter(User.id == other_id).delete()
            cleanup.commit()
        finally:
            cleanup.close()


def test_student_cannot_spoof_teacher_role_to_create_class(client, seeded_ids):
    response = client.post(
        "/login",
        data={
            "username": "李同学",
            "student_id": "S2026001",
            "class_code": f"SPOOF-{uuid4().hex[:10]}",
            "role": "teacher",
            "topic": "不应被创建的课堂",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"status": "error", "message": "课堂不存在，请联系老师"}


def test_end_class_is_idempotent(
    client, lifecycle_meeting, lifecycle_broadcasts
):
    from app.core.database import SessionLocal
    from app.models import Meeting

    assert _start(client, lifecycle_meeting).json()["status"] == "success"

    first = _end(client, lifecycle_meeting)
    assert first.status_code == 200
    assert first.json()["status"] == "success"
    assert first.json()["already_ended"] is False
    assert first.json()["meeting_status"] == "ended"

    db = SessionLocal()
    try:
        first_ended_at = (
            db.query(Meeting).filter(Meeting.id == lifecycle_meeting).one().ended_at
        )
    finally:
        db.close()
    assert first_ended_at is not None

    second = _end(client, lifecycle_meeting)
    assert second.status_code == 200
    assert second.json()["status"] == "success"
    assert second.json()["already_ended"] is True

    db = SessionLocal()
    try:
        meeting = db.query(Meeting).filter(Meeting.id == lifecycle_meeting).one()
        assert meeting.status == "ended"
        assert meeting.ended_at == first_ended_at
    finally:
        db.close()

    assert [payload["type"] for _, payload in lifecycle_broadcasts] == ["class_ended"]


def test_ended_class_cannot_be_restarted(client, lifecycle_meeting, lifecycle_broadcasts):
    assert _start(client, lifecycle_meeting).json()["status"] == "success"
    assert _end(client, lifecycle_meeting).json()["status"] == "success"

    response = _start(client, lifecycle_meeting)
    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert "不能重新开始" in response.json()["message"]


def test_created_class_rejects_running_only_operation(client, lifecycle_meeting):
    response = client.post(
        "/api/quick-decompose", data={"meeting_id": lifecycle_meeting}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert "尚未开始" in response.json()["message"]
