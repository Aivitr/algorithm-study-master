"""Personal overview contract, zero values, time buckets and empty records."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock


def test_personal_overview_buckets_and_zero_scores():
    from app.services.student_classroom_service import build_student_classroom_overview

    origin = datetime(2026, 1, 1)
    meeting = SimpleNamespace(
        id=1,
        started_at=origin,
        created_at=origin,
        topic="test",
        class_code="X",
        status="running",
        knowledge_points=[],
    )
    student = SimpleNamespace(id=7, username="student", student_id="S7")
    rows = [
        SimpleNamespace(
            id=i,
            timestamp=origin + timedelta(seconds=seconds),
            content="hello",
            quality_score=0,
            relevance_score=0,
            quality_feedback=None,
        )
        for i, seconds in [(1, 299), (2, 300)]
    ]
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.side_effect = [rows, []]
    result = build_student_classroom_overview(db, meeting, student)
    assert result["summary"] == {"speech_count": 2, "average_quality": 0, "average_relevance": 0}
    assert [item["count"] for item in result["distribution"]] == [1, 1]
    assert [item["bucket"] for item in result["speeches"]] == [0, 1]
    assert result["emotions"] == []


def test_personal_overview_empty():
    from app.services.student_classroom_service import build_student_classroom_overview

    origin = datetime(2026, 1, 1)
    meeting = SimpleNamespace(
        id=1,
        started_at=None,
        created_at=origin,
        topic="test",
        class_code="X",
        status="created",
        knowledge_points=[],
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    result = build_student_classroom_overview(
        db, meeting, SimpleNamespace(id=7, username="student", student_id="S7")
    )
    assert result["summary"]["average_quality"] is None
    assert result["distribution"] == result["speeches"] == result["emotions"] == []
