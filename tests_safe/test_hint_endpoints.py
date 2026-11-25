"""Hint 候选生成、教师确认/忽略与学生响应。"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.models import AnalysisRun, HintLog, Meeting


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
        db.query(AnalysisRun).filter(AnalysisRun.meeting_id == meeting.id).delete()
        db.query(HintLog).filter(HintLog.meeting_id == meeting.id).delete()
        db.query(Meeting).filter(Meeting.id == meeting.id).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture
def hint_mocks(monkeypatch):
    """拦截 LLM 与 WebSocket；发送只允许在教师确认时发生。"""
    import app.services.hint_candidate_service as hints

    broadcasts = []
    personal = []
    suggestions = []
    hint_contexts = []

    async def fake_broadcast(meeting_id, payload):
        broadcasts.append((meeting_id, payload))

    async def fake_send(meeting_id, username, payload):
        personal.append((meeting_id, username, payload))

    def fake_suggestion(topic, context, knowledge_points, target_type="group", hint_context=""):
        suggestions.append(target_type)
        hint_contexts.append(hint_context)
        return "测试建议", {"prompt_tokens": 10, "completion_tokens": 5}

    monkeypatch.setattr(hints.llm, "generate_topic_suggestion_with_usage", fake_suggestion)
    monkeypatch.setattr(hints.manager, "broadcast_to_meeting", fake_broadcast)
    monkeypatch.setattr(hints.manager, "send_to_user", fake_send)
    return broadcasts, personal, suggestions, hint_contexts


def _stub_candidates(monkeypatch, candidates):
    import app.services.hint_candidate_service as hints

    monkeypatch.setattr(
        hints,
        "evaluate_hint_candidates",
        lambda meeting_id, db: {"status": "success", "candidates": candidates},
    )


def _logs(meeting_id):
    from app.core import database

    db = database.SessionLocal()
    try:
        return db.query(HintLog).filter(HintLog.meeting_id == meeting_id).order_by(HintLog.id).all()
    finally:
        db.close()


def test_check_silence_creates_pending_hint_without_sending(
    client, running_meeting, teacher_headers, hint_mocks, monkeypatch
):
    broadcasts, _personal, suggestions, hint_contexts = hint_mocks
    _stub_candidates(monkeypatch, [_candidate("discussion_stall")])

    response = client.post(
        "/api/check-silence",
        data={"meeting_id": running_meeting.id},
        headers=teacher_headers,
    )

    body = response.json()
    assert body["status"] == "success"
    assert body["silent"] is True
    assert body["pending"][0]["text"] == "测试建议"
    assert suggestions == ["group"]
    assert "触发原因：测试触发原因" in hint_contexts[0]
    assert broadcasts == []

    log = _logs(running_meeting.id)[0]
    assert log.status == "candidate"
    assert log.hint_type == "discussion_stall"
    assert log.target_type == "group"
    assert log.sent_at is None
    assert log.created_by == running_meeting.teacher_id
    assert f"M:{running_meeting.id}" in log.evidence_ids

    from app.core import database

    db = database.SessionLocal()
    try:
        run = (
            db.query(AnalysisRun)
            .filter(
                AnalysisRun.meeting_id == running_meeting.id,
                AnalysisRun.kind == "hint_llm",
            )
            .one()
        )
    finally:
        db.close()
    assert run.status == "success"
    assert run.prompt_tokens == 10
    assert run.latency_ms is not None


def test_check_silence_without_candidate_returns_empty(
    client, running_meeting, teacher_headers, hint_mocks, monkeypatch
):
    _stub_candidates(monkeypatch, [])

    response = client.post(
        "/api/check-silence",
        data={"meeting_id": running_meeting.id},
        headers=teacher_headers,
    )

    assert response.json() == {"status": "success", "silent": False, "pending": []}
    assert _logs(running_meeting.id) == []


def test_duplicate_candidate_is_not_created_twice(
    client, running_meeting, teacher_headers, hint_mocks, monkeypatch
):
    _stub_candidates(monkeypatch, [_candidate("discussion_stall")])

    first = client.post(
        "/api/check-silence",
        data={"meeting_id": running_meeting.id},
        headers=teacher_headers,
    )
    second = client.post(
        "/api/check-silence",
        data={"meeting_id": running_meeting.id},
        headers=teacher_headers,
    )

    assert len(first.json()["pending"]) == 1
    assert second.json()["pending"] == []
    assert len(_logs(running_meeting.id)) == 1


def test_llm_failure_uses_template(
    client, running_meeting, teacher_headers, hint_mocks, monkeypatch
):
    import app.services.hint_candidate_service as hints

    def boom(*args, **kwargs):
        raise RuntimeError("llm down")

    monkeypatch.setattr(hints.llm, "generate_topic_suggestion_with_usage", boom)
    _stub_candidates(monkeypatch, [_candidate("discussion_stall")])

    response = client.post(
        "/api/check-silence",
        data={"meeting_id": running_meeting.id},
        headers=teacher_headers,
    )

    body = response.json()
    assert body["pending"][0]["text"]
    log = _logs(running_meeting.id)[0]
    assert log.model == "template"
    assert log.status == "candidate"


def test_check_quiet_members_creates_student_candidate(
    client, running_meeting, teacher_headers, seeded_ids, hint_mocks, monkeypatch
):
    _broadcasts, personal, suggestions, hint_contexts = hint_mocks
    _stub_candidates(
        monkeypatch,
        [_candidate("low_participation", str(seeded_ids["student_id"]))],
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
    assert "测试触发原因" in hint_contexts[0]
    assert personal == []

    log = _logs(running_meeting.id)[0]
    assert log.hint_type == "low_participation"
    assert log.target_type == "student"
    assert log.target_user_id == str(seeded_ids["student_id"])
    assert log.status == "candidate"


def test_hint_logs_are_teacher_only(
    client, running_meeting, seeded_ids, teacher_headers, student_headers
):
    hint_id = _hint_log(running_meeting.id)

    anonymous = client.get(f"/api/hint-logs/{running_meeting.id}")
    assert anonymous.status_code == 401

    forbidden = client.get(f"/api/hint-logs/{running_meeting.id}", headers=student_headers)
    assert forbidden.status_code == 403

    response = client.get(f"/api/hint-logs/{running_meeting.id}", headers=teacher_headers)
    assert response.status_code == 200
    body = response.json()
    row = next(item for item in body["logs"] if item["id"] == hint_id)
    assert row["evidence_id"] == f"H#{hint_id}"
    assert row["trigger_reason"] == "测试原因"
    assert row["target_name"] == "李同学"


def test_hint_logs_missing_meeting_is_404(client, teacher_headers):
    response = client.get("/api/hint-logs/999999", headers=teacher_headers)
    assert response.status_code == 404


def test_teacher_sends_group_hint(client, running_meeting, teacher_headers, hint_mocks):
    broadcasts, personal, _suggestions, _contexts = hint_mocks
    hint_id = _hint_log(
        running_meeting.id, target_type="group", target_user_id=None, status="candidate"
    )

    response = client.post(f"/api/hint-logs/{hint_id}/send", headers=teacher_headers)

    assert response.status_code == 200
    assert broadcasts[0][1]["type"] == "topic_suggestion"
    assert broadcasts[0][1]["hint_id"] == hint_id
    assert broadcasts[0][1]["reason"] == "group_silence"
    assert personal == []
    log = _logs(running_meeting.id)[0]
    assert log.status == "sent"
    assert log.sent_at is not None


def test_teacher_sends_personal_hint(
    client, running_meeting, seeded_ids, teacher_headers, hint_mocks
):
    broadcasts, personal, _suggestions, _contexts = hint_mocks
    hint_id = _hint_log(
        running_meeting.id,
        target_type="student",
        target_user_id=str(seeded_ids["student_id"]),
        status="candidate",
    )

    response = client.post(f"/api/hint-logs/{hint_id}/send", headers=teacher_headers)

    assert response.status_code == 200
    assert broadcasts == []
    assert personal[0][1] == "李同学"
    assert personal[0][2]["target"] == "personal"
    assert personal[0][2]["hint_id"] == hint_id


def test_teacher_ignores_hint(client, running_meeting, teacher_headers):
    hint_id = _hint_log(running_meeting.id, status="candidate")

    response = client.post(f"/api/hint-logs/{hint_id}/ignore", headers=teacher_headers)

    assert response.json()["hint_status"] == "ignored"
    assert _logs(running_meeting.id)[0].status == "ignored"


def test_sending_an_already_handled_hint_is_rejected(client, running_meeting, teacher_headers):
    hint_id = _hint_log(running_meeting.id, status="ignored")

    response = client.post(f"/api/hint-logs/{hint_id}/send", headers=teacher_headers)

    assert response.status_code == 409


def test_hint_response_personal_target(client, seeded_ids, student_headers):
    hint_id = _hint_log(seeded_ids["meeting_id"])
    response = client.post(
        f"/api/hint-logs/{hint_id}/response",
        json={"response": "acknowledged"},
        headers=student_headers,
    )
    assert response.status_code == 200
    assert response.json()["response"] == "acknowledged"
    assert _logs(seeded_ids["meeting_id"])[0].response == "acknowledged"


def test_hint_response_requires_sent_status(client, seeded_ids, student_headers):
    hint_id = _hint_log(seeded_ids["meeting_id"], status="candidate")

    response = client.post(
        f"/api/hint-logs/{hint_id}/response",
        json={"response": "acknowledged"},
        headers=student_headers,
    )

    assert response.status_code == 409


def test_hint_response_rejects_other_student(client, seeded_ids):
    from app.core import database
    from app.services.session_service import create_session

    hint_id = _hint_log(seeded_ids["meeting_id"])
    db = database.SessionLocal()
    try:
        token, _ = create_session(db, seeded_ids["student_id_b"], device_id="hint-other")
    finally:
        db.close()

    response = client.post(
        f"/api/hint-logs/{hint_id}/response",
        json={"response": "acknowledged"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_hint_response_rejects_teacher(client, seeded_ids, teacher_headers):
    hint_id = _hint_log(seeded_ids["meeting_id"])

    response = client.post(
        f"/api/hint-logs/{hint_id}/response",
        json={"response": "acknowledged"},
        headers=teacher_headers,
    )
    assert response.status_code == 403


def test_hint_response_group_target_requires_participation(client, seeded_ids, student_headers):
    hint_id = _hint_log(seeded_ids["meeting_id"], target_type="group", target_user_id=None)

    response = client.post(
        f"/api/hint-logs/{hint_id}/response",
        json={"response": "need_help"},
        headers=student_headers,
    )
    assert response.status_code == 200


def test_hint_response_missing_is_404(client, student_headers):
    response = client.post(
        "/api/hint-logs/999999/response",
        json={"response": "acknowledged"},
        headers=student_headers,
    )
    assert response.status_code == 404


def _hint_log(
    meeting_id,
    target_type="student",
    target_user_id="2",
    status="sent",
):
    from app.core import database

    db = database.SessionLocal()
    try:
        row = HintLog(
            meeting_id=meeting_id,
            dedupe_key=f"{target_type}:{target_user_id}:test:{status}",
            hint_type="low_participation" if target_type == "student" else "discussion_stall",
            target_type=target_type,
            target_user_id=target_user_id,
            trigger_reason="测试原因",
            evidence={"silence_seconds": 130},
            evidence_ids=[],
            text="测试建议",
            status=status,
            created_by=1,
            sent_at=datetime.now() if status == "sent" else None,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def test_pending_inbox_is_capped(client, running_meeting, teacher_headers, hint_mocks, monkeypatch):
    from app.services.hint_candidate_service import MAX_PENDING_HINTS

    for index in range(MAX_PENDING_HINTS):
        _hint_log(
            running_meeting.id,
            target_type="group",
            target_user_id=None,
            status="candidate",
        )
    _stub_candidates(monkeypatch, [_candidate("discussion_stall")])

    response = client.post(
        "/api/check-silence",
        data={"meeting_id": running_meeting.id},
        headers=teacher_headers,
    )

    assert response.json()["pending"] == []
