"""课堂 Agent 两条 HTTP 接口的无网络契约测试。"""

import app.routers.agents as agent_routes
from app.agents.group_analysis_agent import GroupAnalysisOutput, StructureSummary


def _output() -> GroupAnalysisOutput:
    return GroupAnalysisOutput(
        summary="测试摘要",
        structure=StructureSummary(),
        metrics_reading=[],
        findings=[],
        interventions=[],
        product_metrics=[],
        data_gaps=[],
        unsupported_claims=[],
    )


def test_group_analysis_tools_endpoint(client):
    response = client.get("/api/agents/group-analysis/tools")

    assert response.status_code == 200
    tools = response.json()["tools"]
    assert [tool["name"] for tool in tools] == [
        "get_classroom_transcripts",
        "get_classroom_statistics",
        "get_classroom_knowledge",
        "get_class_metrics",
        "get_engagement",
        "get_hint_history",
    ]
    assert all(tool["allowed_states"] == ["ended", "running"] for tool in tools)


def test_group_analysis_question_endpoint(client, teacher_headers, monkeypatch):
    async def fake_run(db, meeting_id, question, max_turns):
        assert meeting_id == 1
        assert question == "分析参与是否均衡"
        assert max_turns == 6
        return _output()

    monkeypatch.setattr(agent_routes, "run_group_analysis", fake_run)
    response = client.post(
        "/api/agents/group-analysis",
        json={"meeting_id": 1, "question": "分析参与是否均衡", "max_turns": 6},
        headers=teacher_headers,
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "analysis": _output().model_dump()}


def _confirm_payload(meeting_id: int = 1) -> dict:
    return {
        "meeting_id": meeting_id,
        "target": "李同学",
        "action": "点名发言",
        "script": "请李同学补充一个例子",
        "expected": "让沉默成员参与",
        "risk": "可能打断当前讨论",
        "evidence": ["T#1"],
    }


def test_confirm_action_requires_session(client):
    response = client.post("/api/agents/group-analysis/actions/confirm", json=_confirm_payload())
    assert response.status_code == 401


def test_confirm_action_rejects_student(client, student_headers):
    response = client.post(
        "/api/agents/group-analysis/actions/confirm",
        json=_confirm_payload(),
        headers=student_headers,
    )
    assert response.status_code == 403


def test_confirm_action_writes_audit_insight(client, seeded_ids, teacher_headers):
    import json

    from app.core import database
    from app.models import AIInsight

    response = client.post(
        "/api/agents/group-analysis/actions/confirm",
        json=_confirm_payload(seeded_ids["meeting_id"]),
        headers=teacher_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True

    db = database.SessionLocal()
    try:
        insight = db.query(AIInsight).filter(AIInsight.id == body["confirmation_id"]).one()
        payload = json.loads(insight.content)
    finally:
        db.query(AIInsight).filter(AIInsight.id == body["confirmation_id"]).delete()
        db.commit()
        db.close()

    assert insight.type == "agent_action_confirm"
    assert insight.target_user == "李同学"
    assert payload["action"] == "点名发言"
    assert payload["operator_id"] == seeded_ids["teacher_id"]
    assert payload["evidence"] == ["T#1"]


def test_confirm_action_rejects_created_meeting(client, seeded_ids, teacher_headers):
    from datetime import datetime
    from uuid import uuid4

    from app.core import database
    from app.models import Meeting

    db = database.SessionLocal()
    try:
        meeting = Meeting(
            class_code=f"CONFIRM-{uuid4().hex[:8]}",
            teacher_id=seeded_ids["teacher_id"],
            topic="未开始课堂",
            knowledge_points=[],
            status="created",
            created_at=datetime.now(),
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
        meeting_id = meeting.id
    finally:
        db.close()

    try:
        response = client.post(
            "/api/agents/group-analysis/actions/confirm",
            json=_confirm_payload(meeting_id),
            headers=teacher_headers,
        )
        assert response.status_code == 409
    finally:
        cleanup = database.SessionLocal()
        try:
            cleanup.query(Meeting).filter(Meeting.id == meeting_id).delete()
            cleanup.commit()
        finally:
            cleanup.close()


def test_confirm_action_missing_meeting_is_404(client, teacher_headers):
    response = client.post(
        "/api/agents/group-analysis/actions/confirm",
        json=_confirm_payload(999999),
        headers=teacher_headers,
    )
    assert response.status_code == 404


def test_ignore_action_and_history(client, seeded_ids, teacher_headers):
    response = client.post(
        "/api/agents/group-analysis/actions/ignore",
        json=_confirm_payload(seeded_ids["meeting_id"]),
        headers=teacher_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"

    history = client.get(
        f"/api/agents/group-analysis/actions/{seeded_ids['meeting_id']}",
        headers=teacher_headers,
    )
    assert history.status_code == 200
    items = history.json()["items"]
    assert items[0]["status"] == "ignored"
    assert items[0]["action"] == "点名发言"
    assert items[0]["operator_id"] == seeded_ids["teacher_id"]

    from app.core import database
    from app.models import AIInsight

    db = database.SessionLocal()
    try:
        db.query(AIInsight).filter(AIInsight.id == items[0]["audit_id"]).delete()
        db.commit()
    finally:
        db.close()


def test_action_history_is_teacher_only(client, seeded_ids, student_headers):
    response = client.get(
        f"/api/agents/group-analysis/actions/{seeded_ids['meeting_id']}",
        headers=student_headers,
    )
    assert response.status_code == 403


def test_action_history_requires_session(client, seeded_ids):
    response = client.get(f"/api/agents/group-analysis/actions/{seeded_ids['meeting_id']}")
    assert response.status_code == 401
