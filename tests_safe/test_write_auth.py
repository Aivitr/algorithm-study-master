from __future__ import annotations


def test_ai_tutor_requires_session(client):
    response = client.post("/api/ai-tutor", data={"question": "1+1=?"})
    assert response.status_code == 401


def test_group_analysis_requires_session(client):
    response = client.post(
        "/api/agents/group-analysis",
        json={"meeting_id": 1, "question": "分析参与是否均衡", "max_turns": 6},
    )
    assert response.status_code == 401


def test_group_analysis_rejects_student(client, student_headers):
    response = client.post(
        "/api/agents/group-analysis",
        json={"meeting_id": 1, "question": "分析参与是否均衡", "max_turns": 6},
        headers=student_headers,
    )
    assert response.status_code == 403


def test_submit_answer_requires_session(client):
    response = client.post(
        "/api/submit-answer",
        data={"exercise_id": 1, "user_id": 2, "answer_content": "x", "is_correct": 1},
    )
    assert response.status_code == 401


def test_student_cannot_submit_for_another_user(client, seeded_ids, student_headers):
    response = client.post(
        "/api/submit-answer",
        data={
            "exercise_id": 1,
            "user_id": seeded_ids["student_id_b"],
            "answer_content": "x",
            "is_correct": 1,
        },
        headers=student_headers,
    )
    assert response.status_code == 200
    assert response.json() == {"status": "error", "message": "只能提交自己的答题记录"}


def test_browser_asr_final_rejects_other_user(client, student_headers):
    response = client.post(
        "/api/browser-asr-final",
        data={"meeting_id": 1, "username": "S2026002", "text": "冒名"},
        headers=student_headers,
    )
    assert response.status_code == 200
    assert response.json() == {"status": "error", "message": "只能回写自己的识别结果"}


def test_teacher_only_checks_reject_student(client, seeded_ids, student_headers):
    for path in ("/api/check-silence", "/api/check-quiet-members"):
        response = client.post(
            path,
            data={"meeting_id": seeded_ids["meeting_id"]},
            headers=student_headers,
        )
        assert response.status_code == 200
        assert response.json()["message"] == "只有本课堂教师可以触发检查"


def test_pdf_report_requires_session(client):
    response = client.post("/api/generate-pdf-report", data={"meeting_id": 1, "user_id": 2})
    assert response.status_code == 401
