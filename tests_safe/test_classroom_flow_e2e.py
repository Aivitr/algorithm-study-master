from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import pytest


@pytest.fixture
def flow_meeting(seeded_ids):
    from app.core.database import SessionLocal
    from app.models import Meeting

    db = SessionLocal()
    meeting = Meeting(
        class_code=f"E2E-{uuid4().hex[:10]}",
        teacher_id=seeded_ids["teacher_id"],
        topic="端到端课堂流程",
        status="created",
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
        from app.models import ActiveClassroomSession, LearningReport, Transcript

        cleanup = SessionLocal()
        try:
            cleanup.query(Transcript).filter(Transcript.meeting_id == meeting_id).delete()
            cleanup.query(LearningReport).filter(LearningReport.meeting_id == meeting_id).delete()
            cleanup.query(ActiveClassroomSession).filter(
                ActiveClassroomSession.meeting_id == meeting_id
            ).delete()
            cleanup.query(Meeting).filter(Meeting.id == meeting_id).delete()
            cleanup.commit()
        finally:
            cleanup.close()


def test_full_classroom_flow(
    client,
    seeded_ids,
    teacher_headers,
    student_headers,
    flow_meeting,
    monkeypatch,
):
    from app.core.database import SessionLocal
    from app.models import Transcript
    from app.routers import classroom_ops

    scheduled = []
    monkeypatch.setattr(classroom_ops, "schedule_class_reports", scheduled.append)

    started = client.post(
        "/api/start-class",
        data={"meeting_id": flow_meeting, "username": "T2026001"},
        headers=teacher_headers,
    )
    assert started.status_code == 200
    assert started.json()["status"] == "success"

    entered = client.post(
        "/api/classroom/enter",
        json={"meeting_id": flow_meeting},
        headers=student_headers,
    )
    assert entered.status_code == 200

    db = SessionLocal()
    try:
        db.add(
            Transcript(
                meeting_id=flow_meeting,
                user_id=seeded_ids["student_id"],
                content="这是端到端流程里的一条发言",
                created_at=datetime.now(),
            )
        )
        db.commit()
    finally:
        db.close()

    meeting = client.get(f"/api/meeting/{flow_meeting}", headers=teacher_headers)
    assert meeting.status_code == 200
    assert meeting.json()["meeting_status"] == "running"

    transcripts = client.get(f"/api/transcripts/{flow_meeting}", headers=teacher_headers)
    assert transcripts.status_code == 200
    assert any(
        item["text"] == "这是端到端流程里的一条发言" for item in transcripts.json()["transcripts"]
    )

    monkeypatch.setattr("app.routers.realtime.llm.ai_tutor", lambda question: f"回答：{question}")
    tutor = client.post("/api/ai-tutor", data={"question": "1+1=?"}, headers=teacher_headers)
    assert tutor.status_code == 200
    assert tutor.json()["answer"] == "回答：1+1=?"

    left = client.post(
        "/api/classroom/leave",
        json={"meeting_id": flow_meeting},
        headers=student_headers,
    )
    assert left.status_code == 200

    ended = client.post(
        "/api/end-class",
        data={"meeting_id": flow_meeting, "username": "T2026001"},
        headers=teacher_headers,
    )
    assert ended.status_code == 200
    assert ended.json()["status"] == "success"
    assert ended.json()["meeting_status"] == "ended"
    assert scheduled == [flow_meeting]

    reports = client.get(f"/api/meeting-reports/{flow_meeting}", headers=teacher_headers)
    assert reports.status_code == 200
    assert reports.json()["status"] == "success"
