"""注册学号格式：只允许 ASCII 数字。"""


def test_register_rejects_non_numeric_student_id(client):
    response = client.post(
        "/api/register",
        data={
            "student_id": "S2026001",
            "username": "测试用户",
            "password": "Abcdef12345",
            "role": "student",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "error",
        "message": "学号/工号只能包含数字",
    }
