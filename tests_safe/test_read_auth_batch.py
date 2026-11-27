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


def test_read_routes_require_session(client, seeded_ids):
    for path in (
        "/api/meeting/1",
        "/api/transcripts/1",
        f"/api/teacher-stats/{seeded_ids['teacher_id']}",
        "/api/realtime-stats/1",
        f"/api/student-quiz-history/{seeded_ids['student_id']}",
    ):
        assert client.get(path).status_code == 401, path


def test_other_teacher_cannot_read_teacher_stats(client, seeded_ids):
    headers = _headers_for(seeded_ids["student_id_b"], "read-auth-batch-student")
    response = client.get(f"/api/teacher-stats/{seeded_ids['teacher_id']}", headers=headers)
    assert response.status_code == 200
    assert response.json() == {"status": "error", "message": "无权查看其他教师的数据"}


def test_student_cannot_read_other_quiz_history(client, seeded_ids):
    headers = _headers_for(seeded_ids["student_id_b"], "read-auth-batch-student-b")
    response = client.get(f"/api/student-quiz-history/{seeded_ids['student_id']}", headers=headers)
    assert response.status_code == 200
    assert response.json() == {
        "status": "error",
        "message": "无权查看其他学生的答题历史",
    }


def test_student_can_read_own_quiz_history(client, seeded_ids, student_headers):
    response = client.get(
        f"/api/student-quiz-history/{seeded_ids['student_id']}", headers=student_headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_realtime_stats_hides_classmates_from_students(
    client, seeded_ids, student_headers, teacher_headers
):
    path = f"/api/realtime-stats/{seeded_ids['meeting_id']}"

    own = client.get(path, headers=student_headers).json()
    assert own["status"] == "success"
    assert {row["name"] for row in own["pie_data"]} == {"李同学"}
    assert {row["name"] for row in own["member_scores"]} == {"李同学"}
    assert set(own["emotion_timeline"]) == {"李同学"}
    assert own["interaction"]["edges"] == []

    full = client.get(path, headers=teacher_headers).json()
    assert {"李同学", "王同学"} <= {row["name"] for row in full["member_scores"]}
