"""旧 Hint 接口改为消费 GCA 候选后的行为。"""

from __future__ import annotations

import pytest

from app.models import HintLog, Meeting


def _candidate(hint_type, target_user_id=None):
    return {
        "meeting_id": "1",
        "hint_type": hint_type,
        "target_type": "student" if target_user_id else "group",
        "target_user_id": target_user_id,
        "window": {"start_second": 0, "end_second": 300},
        "trigger_reason": "测试触发原因",
        "evidence": {"rule": "test"},
        "data_status": "ok",
        "generated_at": 300.0,
        "dedupe_key": f"{hint_type}:test",
    }


@pytest.fixture
def running_meeting(seeded_ids):
    from app.core import database

    db = database.SessionLocal()
    try:
        meeting = Meeting(
            class_code="HINT-EP-1",
            teacher_id=seeded_ids["teacher_id"],
            topic="Hint 接口测试",
            status="running",
            knowledge_points=[],
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
        yield meeting
        db.query(HintLog).filter(HintLog.meeting_id == meeting.id).delete()
        db.query(Meeting).filter(Meeting.id == meeting.id).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture
def hint_mocks(monkeypatch):
    import app.routers.realtime as realtime

    broadcasts = []
    personal = []
    suggestions = []

    async def fake_broadcast(meeting_id, payload):
        broadcasts.append((meeting_id, payload))

    async def fake_send(meeting_id, username, payload):
        personal.append((meeting_id, username, payload))

    def fake_suggestion(topic, context, knowledge_points, target_type="group"):
        suggestions.append(target_type)
        return "测试建议"

    monkeypatch.setattr(realtime.manager, "broadcast_to_meeting", fake_broadcast)
    monkeypatch.setattr(realtime.manager, "send_to_user", fake_send)
    monkeypatch.setattr(realtime.llm, "generate_topic_suggestion", fake_suggestion)
    return broadcasts, personal, suggestions


def test_check_silence_consumes_stall_candidate(
    client, running_meeting, teacher_headers, hint_mocks, monkeypatch
):
    import app.routers.realtime as realtime

    broadcasts, _personal, suggestions = hint_mocks
    monkeypatch.setattr(
        realtime,
        "evaluate_hint_candidates",
        lambda meeting_id, db: {
            "status": "success",
            "candidates": [_candidate("discussion_stall")],
        },
    )

    response = client.post(
        "/api/check-silence",
        data={"meeting_id": running_meeting.id},
        headers=teacher_headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["suggestion"] == "测试建议"
    assert suggestions == ["group"]
    assert broadcasts[0][1]["reason"] == "group_silence"
    assert broadcasts[0][1]["trigger_reason"] == "测试触发原因"

    from app.core import database

    db = database.SessionLocal()
    try:
        log = db.query(HintLog).filter(HintLog.meeting_id == running_meeting.id).one()
    finally:
        db.close()
    assert log.hint_type == "discussion_stall"
    assert log.target_type == "group"
    assert log.target_user_id is None
    assert log.text == "测试建议"
    assert log.status == "sent"
    assert log.created_by == 1


def test_check_silence_returns_false_without_candidate(
    client, running_meeting, teacher_headers, hint_mocks, monkeypatch
):
    import app.routers.realtime as realtime

    monkeypatch.setattr(
        realtime,
        "evaluate_hint_candidates",
        lambda meeting_id, db: {"status": "success", "candidates": []},
    )

    response = client.post(
        "/api/check-silence",
        data={"meeting_id": running_meeting.id},
        headers=teacher_headers,
    )

    assert response.json() == {"status": "ok", "silent": False}


def test_check_quiet_members_targets_student(
    client, running_meeting, teacher_headers, seeded_ids, hint_mocks, monkeypatch
):
    import app.routers.realtime as realtime

    _broadcasts, personal, suggestions = hint_mocks
    monkeypatch.setattr(
        realtime,
        "evaluate_hint_candidates",
        lambda meeting_id, db: {
            "status": "success",
            "candidates": [_candidate("low_participation", str(seeded_ids["student_id"]))],
        },
    )

    response = client.post(
        "/api/check-quiet-members",
        data={"meeting_id": running_meeting.id},
        headers=teacher_headers,
    )

    body = response.json()
    assert body["status"] == "success"
    assert body["quiet_members"] == ["李同学"]
    assert suggestions == ["quiet"]
    assert personal[0][1] == "李同学"
    assert personal[0][2]["reason"] == "low_participation"
    assert personal[0][2]["trigger_reason"] == "测试触发原因"

    from app.core import database

    db = database.SessionLocal()
    try:
        log = db.query(HintLog).filter(HintLog.meeting_id == running_meeting.id).one()
    finally:
        db.close()
    assert log.hint_type == "low_participation"
    assert log.target_type == "student"
    assert log.target_user_id == str(seeded_ids["student_id"])
    assert log.text == "测试建议"
