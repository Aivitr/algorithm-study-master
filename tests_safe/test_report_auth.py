from __future__ import annotations


def test_generate_report_requires_session(client, seeded_ids):
    response = client.post(
        "/api/generate-report",
        data={"meeting_id": seeded_ids["meeting_id"], "user_id": seeded_ids["student_id"]},
    )
    assert response.status_code == 401


def test_generate_report_denies_other_student(client, seeded_ids, student_headers):
    response = client.post(
        "/api/generate-report",
        data={
            "meeting_id": seeded_ids["meeting_id"],
            "user_id": seeded_ids["student_id_b"],
        },
        headers=student_headers,
    )
    assert response.status_code == 200
    assert response.json() == {"status": "error", "message": "无权生成该学生的报告"}


def test_generate_report_stream_requires_session(client, seeded_ids):
    response = client.post(
        "/api/generate-report-stream",
        data={"meeting_id": seeded_ids["meeting_id"], "user_id": seeded_ids["student_id"]},
    )
    assert response.status_code == 401


def test_generate_report_stream_denies_other_student(client, seeded_ids, student_headers):
    response = client.post(
        "/api/generate-report-stream",
        data={
            "meeting_id": seeded_ids["meeting_id"],
            "user_id": seeded_ids["student_id_b"],
        },
        headers=student_headers,
    )
    assert response.status_code == 403
    assert response.json() == {"status": "error", "message": "无权生成该学生的报告"}
