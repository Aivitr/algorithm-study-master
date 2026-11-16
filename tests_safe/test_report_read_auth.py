from __future__ import annotations


def _headers_for(user_id: int, device_id: str) -> dict:
    from app.core import database
    from app.services.session_service import create_session

    db = database.SessionLocal()
    try:
        token, _ = create_session(db, user_id, device_id=device_id)
    finally:
        db.close()
    return {"Authorization": f"Bearer {token}"}


def test_reports_require_session(client, seeded_ids):
    response = client.get(f"/api/reports/{seeded_ids['student_id']}")
    assert response.status_code == 401


def test_student_can_read_own_reports(client, seeded_ids, student_headers):
    response = client.get(f"/api/reports/{seeded_ids['student_id']}", headers=student_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_student_cannot_read_other_student_reports(client, seeded_ids):
    headers = _headers_for(seeded_ids["student_id_b"], "read-auth-student-b")
    response = client.get(f"/api/reports/{seeded_ids['student_id']}", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"status": "error", "message": "无权查看该用户的报告"}


def test_teacher_can_read_student_reports(client, seeded_ids, teacher_headers):
    response = client.get(f"/api/reports/{seeded_ids['student_id']}", headers=teacher_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_meeting_reports_require_session(client, seeded_ids):
    response = client.get(f"/api/meeting-reports/{seeded_ids['meeting_id']}")
    assert response.status_code == 401


def test_student_cannot_read_meeting_reports(client, seeded_ids, student_headers):
    response = client.get(
        f"/api/meeting-reports/{seeded_ids['meeting_id']}", headers=student_headers
    )
    assert response.status_code == 200
    assert response.json() == {"status": "error", "message": "无权查看该课堂报告"}


def test_exercises_require_session(client, seeded_ids):
    response = client.get(f"/api/exercises/{seeded_ids['report_id']}")
    assert response.status_code == 401


def test_student_cannot_read_other_student_exercises(client, seeded_ids):
    headers = _headers_for(seeded_ids["student_id_b"], "read-auth-student-b-ex")
    response = client.get(f"/api/exercises/{seeded_ids['report_id']}", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"status": "error", "message": "无权查看该报告的习题"}


def test_download_exercises_requires_session(client, seeded_ids):
    response = client.get(f"/api/download-exercises/{seeded_ids['report_id']}")
    assert response.status_code == 401


def test_student_cannot_download_other_student_exercises(client, seeded_ids):
    headers = _headers_for(seeded_ids["student_id_b"], "read-auth-student-b-dl")
    response = client.get(f"/api/download-exercises/{seeded_ids['report_id']}", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"status": "error", "message": "无权下载该报告的习题"}
