"""服务端会话与课堂占用锁的单元/接口测试。"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.models import ActiveClassroomSession, UserSession
from app.services.session_service import (
    ClassroomError,
    claim_classroom,
    create_session,
    get_valid_session,
    hash_token,
    release_classroom,
    session_context,
)


@pytest.fixture(autouse=True)
def clean_sessions(local_app):
    db = SessionLocal()
    try:
        db.query(ActiveClassroomSession).delete(synchronize_session=False)
        db.query(UserSession).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.query(ActiveClassroomSession).delete(synchronize_session=False)
        db.query(UserSession).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _manual_session(db, user_id: int, device_id: str, token: str) -> UserSession:
    now = datetime.now()
    row = UserSession(
        token_hash=hash_token(token),
        user_id=user_id,
        device_id=device_id,
        user_agent="pytest",
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=12),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_create_session_revokes_previous_session(seeded_ids):
    db = SessionLocal()
    try:
        token1, row1 = create_session(db, seeded_ids["student_id"], "device-a")
        assert get_valid_session(db, token1).id == row1.id

        token2, row2 = create_session(db, seeded_ids["student_id"], "device-b")
        db.refresh(row1)
        assert row1.revoked_at is not None
        assert get_valid_session(db, token1) is None
        assert get_valid_session(db, token2).id == row2.id
    finally:
        db.close()


def test_same_device_login_revokes_other_account(seeded_ids):
    db = SessionLocal()
    try:
        token_a, row_a = create_session(db, seeded_ids["student_id"], "shared-device")
        token_b, _ = create_session(db, seeded_ids["student_id_b"], "shared-device")
        db.refresh(row_a)
        assert row_a.revoked_at is not None
        assert get_valid_session(db, token_a) is None
        assert get_valid_session(db, token_b) is not None
    finally:
        db.close()


def test_claim_classroom_conflicts_for_same_user(seeded_ids):
    db = SessionLocal()
    try:
        token1, _ = create_session(db, seeded_ids["student_id"], "device-1")
        ctx1 = session_context(db, token1)
        claim_classroom(db, ctx1, seeded_ids["meeting_id_active"])

        token2 = "manual-token-2"
        _manual_session(db, seeded_ids["student_id"], "device-2", token2)
        ctx2 = session_context(db, token2)
        with pytest.raises(ClassroomError) as exc:
            claim_classroom(db, ctx2, seeded_ids["meeting_id_active"])
        assert exc.value.status_code == 409

        assert release_classroom(db, ctx1.session.id, seeded_ids["meeting_id_active"]) == 1
        claim_classroom(db, ctx2, seeded_ids["meeting_id_active"])
    finally:
        db.close()


def test_claim_classroom_conflicts_for_same_device(seeded_ids):
    db = SessionLocal()
    try:
        token1, _ = create_session(db, seeded_ids["student_id"], "device-x")
        ctx1 = session_context(db, token1)
        claim_classroom(db, ctx1, seeded_ids["meeting_id_active"])

        token2 = "manual-token-3"
        _manual_session(db, seeded_ids["student_id_b"], "device-x", token2)
        ctx2 = session_context(db, token2)
        with pytest.raises(ClassroomError) as exc:
            claim_classroom(db, ctx2, seeded_ids["meeting_id_active"])
        assert exc.value.status_code == 409
    finally:
        db.close()


def test_api_login_issues_session_token(client, seeded_ids, monkeypatch):
    """登录接口应返回 token，并能用该 token 校验会话。"""
    import pymssql

    class FakeCursor:
        def execute(self, *args, **kwargs):
            return None

        def fetchone(self):
            return {
                "id": seeded_ids["student_id"],
                "student_id": "S2026001",
                "username": "李同学",
                "password": "not-a-real-hash",
                "role": "student",
            }

        def close(self):
            return None

    class FakeConnection:
        def cursor(self, as_dict=False):
            return FakeCursor()

        def close(self):
            return None

    monkeypatch.setattr(pymssql, "connect", lambda **kwargs: FakeConnection())

    res = client.post("/api/login", data={
        "student_id": "S2026001",
        "password": "not-a-real-hash",
        "device_id": "login-device",
    })
    body = res.json()
    assert body["status"] == "success"
    assert body["session_token"]
    headers = {"Authorization": f"Bearer {body['session_token']}"}
    assert client.get("/api/session/validate", headers=headers).status_code == 200


def test_session_routes_validate_enter_conflict_and_logout(client, seeded_ids):
    db = SessionLocal()
    try:
        token1, _ = create_session(db, seeded_ids["student_id"], "route-device-1")
        token2 = "manual-route-token-2"
        _manual_session(db, seeded_ids["student_id"], "route-device-2", token2)
    finally:
        db.close()

    headers1 = {"Authorization": f"Bearer {token1}"}
    headers2 = {"Authorization": f"Bearer {token2}"}

    assert client.get("/api/session/validate", headers=headers1).status_code == 200
    assert client.get("/api/session/validate", headers={"Authorization": "Bearer nope"}).status_code == 401

    entered = client.post("/api/classroom/enter", json={"meeting_id": seeded_ids["meeting_id_active"]}, headers=headers1)
    assert entered.status_code == 200

    conflict = client.post("/api/classroom/enter", json={"meeting_id": seeded_ids["meeting_id_active"]}, headers=headers2)
    assert conflict.status_code == 409

    assert client.post("/api/classroom/leave", json={"meeting_id": seeded_ids["meeting_id_active"]}, headers=headers1).status_code == 200
    assert client.post("/api/classroom/enter", json={"meeting_id": seeded_ids["meeting_id_active"]}, headers=headers2).status_code == 200

    assert client.post("/api/logout", headers=headers1).status_code == 200
    assert client.get("/api/session/validate", headers=headers1).status_code == 401
