"""分析运行观测查询接口。"""

from __future__ import annotations

from app.models import AnalysisRun


def test_analysis_runs_requires_session(client, seeded_ids):
    response = client.get(f"/api/analysis-runs/{seeded_ids['meeting_id']}")
    assert response.status_code == 401


def test_analysis_runs_rejects_student(client, seeded_ids, student_headers):
    response = client.get(f"/api/analysis-runs/{seeded_ids['meeting_id']}", headers=student_headers)
    assert response.status_code == 403


def test_analysis_runs_lists_teacher_visible_rows(client, seeded_ids, teacher_headers):
    from app.core import database

    db = database.SessionLocal()
    try:
        row = AnalysisRun(
            meeting_id=seeded_ids["meeting_id"],
            kind="hint_llm",
            source="llm",
            model="deepseek-chat",
            version="topic_suggestion_v1",
            status="success",
            latency_ms=123,
            prompt_tokens=10,
            completion_tokens=5,
            result={"hint_type": "discussion_stall"},
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        run_id = row.id
    finally:
        db.close()

    try:
        response = client.get(
            f"/api/analysis-runs/{seeded_ids['meeting_id']}", headers=teacher_headers
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "success"
        item = next(run for run in body["runs"] if run["id"] == run_id)
        assert item["kind"] == "hint_llm"
        assert item["latency_ms"] == 123
        assert item["prompt_tokens"] == 10
    finally:
        cleanup = database.SessionLocal()
        try:
            cleanup.query(AnalysisRun).filter(AnalysisRun.id == run_id).delete()
            cleanup.commit()
        finally:
            cleanup.close()


def test_analysis_runs_missing_meeting_is_404(client, teacher_headers):
    response = client.get("/api/analysis-runs/999999", headers=teacher_headers)
    assert response.status_code == 404
