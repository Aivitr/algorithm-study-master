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


def test_gca_dashboard_rejects_other_teacher(client, seeded_ids):
    from app.core import database
    from app.models import User, UserSession
    from app.services.session_service import create_session

    db = database.SessionLocal()
    try:
        other = User(
            student_id="T-OTHER",
            username="其他老师",
            password="not-a-real-hash",
            role="teacher",
        )
        db.add(other)
        db.commit()
        db.refresh(other)
        other_id = other.id
        token, _ = create_session(db, other_id, device_id="gca-other-teacher")
    finally:
        db.close()

    try:
        response = client.get(
            f"/api/gca-dashboard/{seeded_ids['meeting_id']}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403
    finally:
        cleanup = database.SessionLocal()
        try:
            cleanup.query(UserSession).filter(UserSession.user_id == other_id).delete()
            cleanup.query(User).filter(User.id == other_id).delete()
            cleanup.commit()
        finally:
            cleanup.close()


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
    assert body["class_average"] == {}
    assert body["timeline"] is None
    assert body["privacy_note"]
    assert body["suggestions"]


def test_student_view_shows_average_with_enough_speakers(seeded_ids, monkeypatch):
    from app.core import database
    from app.models import User
    from app.services import gca_service

    result = {
        "status": "success",
        "student_metrics": {str(seeded_ids["student_id"]): {"participation": 0.25}},
        "group_metrics": {"participation": {"mean": 0.25, "min": 0.2, "max": 0.3}},
        "timeline": {
            "sliding_5min": [
                {"center_second": 30, "group_metrics": {"participation": {"mean": 0.25}}}
            ]
        },
        "metadata": {"n_speakers": 4, "n_utterances": 12, "duration_seconds": 600},
        "warnings": [],
        "error": None,
    }
    monkeypatch.setattr(gca_service, "analyze_meeting_metrics", lambda meeting_id, db: result)

    db = database.SessionLocal()
    try:
        student = db.query(User).filter(User.id == seeded_ids["student_id"]).first()
        view = gca_service.build_gca_student_view(seeded_ids["meeting_id"], student, db)
    finally:
        db.close()

    assert view["class_average"] == {"participation": 0.25}
    assert view["timeline"] is not None
    assert view["privacy_note"] is None


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

    try:
        response = client.get(f"/api/gca-student-view/{meeting_id}", headers=student_headers)
        assert response.status_code == 403
        assert response.json()["detail"] == "你尚未加入该课堂"
    finally:
        cleanup = database.SessionLocal()
        try:
            cleanup.query(Meeting).filter(Meeting.id == meeting_id).delete()
            cleanup.commit()
        finally:
            cleanup.close()
