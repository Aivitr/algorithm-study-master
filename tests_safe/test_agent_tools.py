"""Agent 工具门禁、GCA 指标服务与输出契约。"""

from datetime import datetime
from uuid import uuid4

from app.core import database
from app.agents.group_analysis_agent import (
    GroupAnalysisOutput,
    MetricReading,
    StructureSummary,
)
from app.agents.state import require_tool_state
from app.models import Meeting
from app.services.classroom_agent_service import classroom_agent_service


def _meeting(db, status: str) -> int:
    meeting = Meeting(
        class_code=f"AGENT-{uuid4().hex[:8]}",
        teacher_id=1,
        topic="Agent 门禁测试",
        knowledge_points=[],
        status=status,
        created_at=datetime.now(),
    )
    if status != "created":
        meeting.started_at = datetime.now()
    db.add(meeting)
    db.commit()
    db.refresh(meeting)
    return meeting.id


def test_tool_gate_rejects_created_and_allows_read_states(seeded_ids):
    db = database.SessionLocal()
    created_id = _meeting(db, "created")
    running_id = _meeting(db, "running")
    ended_id = _meeting(db, "ended")
    try:
        denied = require_tool_state("get_class_metrics", db, created_id)
        assert denied is not None
        assert denied["state"] == "created"
        assert denied["allowed"] is False

        assert require_tool_state("get_class_metrics", db, running_id) is None
        assert require_tool_state("get_class_metrics", db, ended_id) is None
    finally:
        db.query(Meeting).filter(
            Meeting.id.in_([created_id, running_id, ended_id])
        ).delete(synchronize_session=False)
        db.commit()
        db.close()


def test_get_metrics_returns_quality_layer(seeded_ids):
    db = database.SessionLocal()
    try:
        result = classroom_agent_service.get_metrics(db, seeded_ids["meeting_id"])
    finally:
        db.close()

    assert result["ok"] is True
    assert result["layer"] == "quality"
    assert set(result["student_metrics"]) == {"2", "3"}


def test_output_contract_has_layers_and_reserved_product_metrics():
    output = GroupAnalysisOutput(
        summary="总结",
        structure=StructureSummary(),
        metrics_reading=[
            MetricReading(
                metric="speech_count",
                layer="facts",
                value=3,
                reading="发言 3 条",
                evidence=["T#1"],
            ),
            MetricReading(
                metric="newness",
                layer="quality",
                value=0.5,
                reading="信息增量中等",
                evidence=["M:newness"],
            ),
        ],
        findings=[],
        interventions=[],
        data_gaps=["小组结构发现未实现"],
        unsupported_claims=[],
    )

    payload = output.model_dump()
    assert {item["layer"] for item in payload["metrics_reading"]} == {
        "facts",
        "quality",
    }
    assert payload["product_metrics"] == []
    assert payload["structure"] == {"groups": [], "bridges": [], "isolates": []}
