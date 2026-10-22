"""MeetingContextService：课堂上下文与 GET /api/meeting/{id} 的响应形状。"""

from datetime import datetime
from types import SimpleNamespace

from app.core import database
from app.services.meeting_context_service import MeetingContextService


def test_route_exposes_state_and_times(client, seeded_ids):
    body = client.get("/api/meeting/1").json()

    assert set(body) == {
        "status",
        "meeting_id",
        "topic",
        "class_status",
        "created_at",
        "started_at",
        "ended_at",
        "goals",
        "teaching_design",
    }, body
    assert body["status"] == "success"
    assert body["meeting_id"] == 1
    assert body["class_status"] == "ended"
    assert body["created_at"].startswith("2026-01-01T09:00:00")
    assert body["ended_at"].startswith("2026-01-01T10:00:00")
    assert body["started_at"] is None  # 状态机任务（A2）尚未加字段
    assert body["goals"] == []
    assert body["teaching_design"] is None


def test_missing_meeting_shape(client):
    assert client.get("/api/meeting/999").json() == {
        "status": "error",
        "message": "课堂不存在",
    }


def test_to_dict_reads_started_at_when_present():
    svc = MeetingContextService(None)
    started = datetime(2026, 1, 1, 9, 30, 0)
    meeting = SimpleNamespace(
        id=7,
        topic="测试",
        status="running",
        created_at=datetime(2026, 1, 1, 9, 0, 0),
        started_at=started,
        ended_at=None,
        knowledge_points=[{"id": 1, "desc": "目标", "status": "pending"}],
        teaching_design={"steps": []},
    )

    body = svc.to_dict(meeting)

    assert body["class_status"] == "running"
    assert body["started_at"] == started.isoformat()
    assert body["ended_at"] is None
    assert body["goals"] == [{"id": 1, "desc": "目标", "status": "pending"}]


def test_to_dict_tolerates_model_without_started_at():
    svc = MeetingContextService(None)
    meeting = SimpleNamespace(
        id=8, topic="旧模型", status="active",
        created_at=datetime(2026, 1, 1, 9, 0, 0),
        ended_at=None, knowledge_points=None, teaching_design=None,
    )

    body = svc.to_dict(meeting)

    assert "started_at" in body and body["started_at"] is None
    assert body["goals"] == []


def test_service_reads_meeting(seeded_ids):
    db = database.SessionLocal()
    try:
        body = MeetingContextService(db).build_response(seeded_ids["meeting_id"])
    finally:
        db.close()

    assert body["status"] == "success"
    assert body["topic"] == "测试课堂：光合作用"
    assert body["class_status"] == "ended"
