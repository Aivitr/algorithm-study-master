"""Role-scoped GCA dashboard HTTP contracts."""


def test_gca_dashboard_requires_login(client, seeded_ids):
    response = client.get(f"/api/gca-dashboard/{seeded_ids['meeting_id']}")
    assert response.status_code == 401


def test_gca_dashboard_rejects_student(client, seeded_ids, student_headers):
    response = client.get(f"/api/gca-dashboard/{seeded_ids['meeting_id']}", headers=student_headers)
    assert response.status_code == 403


def test_gca_dashboard_returns_named_students_for_owner(client, seeded_ids, teacher_headers):
    response = client.get(f"/api/gca-dashboard/{seeded_ids['meeting_id']}", headers=teacher_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert set(body["group_metrics"]) == {
        "participation",
        "internal_cohesion",
        "overall_responsivity",
        "social_impact",
        "newness",
        "communication_density",
    }
    assert {student["name"] for student in body["students"]} == {"李同学", "王同学"}
    assert all(student["utterance_count"] > 0 for student in body["students"])
    assert body["signals"]


def test_gca_dashboard_returns_404_for_missing_meeting(client, teacher_headers):
    response = client.get("/api/gca-dashboard/999999", headers=teacher_headers)
    assert response.status_code == 404


def test_student_gca_view_rejects_teacher(client, seeded_ids, teacher_headers):
    response = client.get(
        f"/api/gca-student-view/{seeded_ids['meeting_id']}", headers=teacher_headers
    )
    assert response.status_code == 403


def test_student_gca_view_contains_only_current_student(client, seeded_ids, student_headers):
    response = client.get(
        f"/api/gca-student-view/{seeded_ids['meeting_id']}", headers=student_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["student"]["id"] == str(seeded_ids["student_id"])
    assert body["student"]["name"] == "李同学"
    assert "students" not in body
    assert "student_metrics" not in body
    assert "王同学" not in response.text
    assert set(body["class_average"]) == {
        "participation",
        "internal_cohesion",
        "overall_responsivity",
        "social_impact",
        "newness",
        "communication_density",
    }
    assert body["suggestions"]
    for window in (body.get("timeline") or {}).get("sliding_5min", []):
        for stats in window.get("group_metrics", {}).values():
            assert set(stats) == {"mean"}


def test_student_gca_view_requires_participation(client, seeded_ids, student_headers):
    from app.core import database
    from app.models import Meeting

    db = database.SessionLocal()
    try:
        meeting = Meeting(
            class_code="GCA-NOT-JOINED",
            teacher_id=seeded_ids["teacher_id"],
            topic="未参与课堂",
            status="running",
            knowledge_points=[],
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)
        meeting_id = meeting.id
    finally:
        db.close()

    response = client.get(f"/api/gca-student-view/{meeting_id}", headers=student_headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "你尚未加入该课堂"
