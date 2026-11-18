from __future__ import annotations


def test_research_runtime_requires_session(client):
    response = client.post("/api/research-runtime/config", data={"deployment_profile": "base"})
    assert response.status_code == 401


def test_research_runtime_rejects_student(client, student_headers):
    response = client.post(
        "/api/research-runtime/config",
        data={"deployment_profile": "base"},
        headers=student_headers,
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "error",
        "message": "只有教师可以修改运行时配置",
    }


def test_delete_template_requires_session(client, seeded_ids):
    response = client.delete(f"/api/delete-template/{seeded_ids['template_id']}")
    assert response.status_code == 401


def test_delete_template_rejects_student(client, seeded_ids, student_headers):
    response = client.delete(
        f"/api/delete-template/{seeded_ids['template_id']}", headers=student_headers
    )
    assert response.status_code == 200
    assert response.json() == {"status": "error", "message": "只能删除自己的模板"}


def test_voiceprint_register_rejects_other_identity(client, student_headers):
    response = client.post(
        "/api/voiceprint/register",
        data={"username": "S2026002"},
        files={"audio": ("x.wav", b"RIFF", "audio/wav")},
        headers=student_headers,
    )
    assert response.status_code == 200
    assert response.json() == {"status": "error", "message": "只能绑定自己的声纹"}


def test_voiceprint_unregister_rejects_other_identity(client, student_headers):
    response = client.delete("/api/voiceprint/unregister/S2026002", headers=student_headers)
    assert response.status_code == 200
    assert response.json() == {"status": "error", "message": "只能删除自己的声纹"}


def test_cast_vote_requires_session(client):
    response = client.post(
        "/api/cast-vote",
        data={"vote_id": 1, "viewpoint_id": 1, "username": "李同学", "meeting_id": 1},
    )
    assert response.status_code == 401


def test_cast_vote_rejects_other_identity(client, student_headers):
    response = client.post(
        "/api/cast-vote",
        data={"vote_id": 1, "viewpoint_id": 1, "username": "S2026002", "meeting_id": 1},
        headers=student_headers,
    )
    assert response.status_code == 200
    assert response.json() == {"status": "error", "message": "只能以自己的身份投票"}
