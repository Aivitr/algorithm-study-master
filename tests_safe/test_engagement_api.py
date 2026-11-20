"""三维投入读取接口：权限与过滤。"""

from __future__ import annotations

import pytest

from app.models.engagement import EngagementCurve


@pytest.fixture
def curves(seeded_ids):
    from app.core import database

    db = database.SessionLocal()
    try:
        rows = [
            EngagementCurve(
                meeting_id=seeded_ids["meeting_id"],
                user_id=seeded_ids["student_id"],
                dimension="emotional",
                window_start_second=0.0,
                window_end_second=300.0,
                metrics={"positive_ratio": 0.6},
                status="ok",
                protocol_version="1.0",
            ),
            EngagementCurve(
                meeting_id=seeded_ids["meeting_id"],
                user_id=seeded_ids["student_id"],
                dimension="behavioral",
                window_start_second=300.0,
                window_end_second=600.0,
                metrics={"utterance_count": 3},
                status="ok",
                protocol_version="1.0",
            ),
            EngagementCurve(
                meeting_id=seeded_ids["meeting_id"],
                user_id=seeded_ids["student_id_b"],
                dimension="emotional",
                window_start_second=0.0,
                window_end_second=300.0,
                metrics={"positive_ratio": 0.2},
                status="ok",
                protocol_version="1.0",
            ),
            EngagementCurve(
                meeting_id=seeded_ids["meeting_id"],
                user_id=None,
                dimension="cognitive",
                window_start_second=0.0,
                window_end_second=300.0,
                metrics={"quality_mean": 80.0},
                status="ok",
                protocol_version="1.0",
            ),
        ]
        db.add_all(rows)
        db.commit()
        yield
        for row in rows:
            db.delete(row)
        db.commit()
    finally:
        db.close()


def test_engagement_requires_session(client, seeded_ids):
    response = client.get(f"/api/engagement/{seeded_ids['meeting_id']}")
    assert response.status_code == 401


def test_teacher_sees_all_curves_for_own_meeting(client, seeded_ids, teacher_headers, curves):
    response = client.get(f"/api/engagement/{seeded_ids['meeting_id']}", headers=teacher_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert len(data["curves"]) == 4
    assert data["curves"][0]["window_start_second"] == 0.0


def test_student_sees_only_own_curves(client, seeded_ids, student_headers, curves):
    response = client.get(f"/api/engagement/{seeded_ids['meeting_id']}", headers=student_headers)
    assert response.status_code == 200
    data = response.json()
    assert {row["user_id"] for row in data["curves"]} == {seeded_ids["student_id"]}
    assert {row["dimension"] for row in data["curves"]} == {"emotional", "behavioral"}


def test_student_cannot_query_another_student(client, seeded_ids, student_headers, curves):
    response = client.get(
        f"/api/engagement/{seeded_ids['meeting_id']}",
        params={"user_id": seeded_ids["student_id_b"]},
        headers=student_headers,
    )
    assert response.status_code == 403


def test_dimension_filter(client, seeded_ids, teacher_headers, curves):
    response = client.get(
        f"/api/engagement/{seeded_ids['meeting_id']}",
        params={"dimension": "emotional"},
        headers=teacher_headers,
    )
    assert response.status_code == 200
    assert {row["dimension"] for row in response.json()["curves"]} == {"emotional"}


def test_invalid_dimension_is_rejected(client, seeded_ids, teacher_headers, curves):
    response = client.get(
        f"/api/engagement/{seeded_ids['meeting_id']}",
        params={"dimension": "unknown"},
        headers=teacher_headers,
    )
    assert response.status_code == 422


def test_unknown_meeting_is_404(client, seeded_ids, teacher_headers):
    response = client.get("/api/engagement/999999", headers=teacher_headers)
    assert response.status_code == 404
