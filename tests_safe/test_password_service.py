from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("LLM_API_KEY", "test-key")

from app.routers import auth  # noqa: E402
from app.services.password_service import (  # noqa: E402
    hash_password,
    is_legacy_password,
    validate_password_strength,
    verify_password,
)


class _Cursor:
    def __init__(self, row=None):
        self.row = row
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))

    def fetchone(self):
        return self.row

    def close(self):
        pass


class _Conn:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.committed = False

    def cursor(self, as_dict=False):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def close(self):
        pass


def _request(host="127.0.0.1"):
    return SimpleNamespace(headers={}, client=SimpleNamespace(host=host))


def test_hash_roundtrip_and_salt():
    first = hash_password("password123")
    second = hash_password("password123")
    assert first != second
    assert first.startswith("scrypt$")
    assert verify_password("password123", first)
    assert not verify_password("password124", first)


def test_legacy_password_still_verifies_and_is_detected():
    assert is_legacy_password("old-plain")
    assert not is_legacy_password(hash_password("password123"))
    assert verify_password("old-plain", "old-plain")
    assert not verify_password("wrong", "old-plain")


def test_password_strength():
    assert validate_password_strength("Short1") == "密码长度不能少于10位"
    assert validate_password_strength("a" * 129) == "密码不能超过 128 位"
    assert validate_password_strength("password123") == "密码必须包含至少一个大写字母"
    assert validate_password_strength("PASSWORD123") == "密码必须包含至少一个小写字母"
    assert validate_password_strength("PasswordOnly") == "密码必须包含至少一个数字"
    assert validate_password_strength("Password123") is None


def test_register_hashes_password(monkeypatch):
    cursor = _Cursor()
    conn = _Conn(cursor)
    monkeypatch.setattr("pymssql.connect", lambda **kwargs: conn)

    result = asyncio.run(
        auth.register(_request("127.0.0.10"), "2026001", "测试学生", "Password123", "student")
    )

    assert result["status"] == "success"
    _, params = cursor.calls[0]
    assert params[2] != "Password123"
    assert verify_password("Password123", params[2])
    assert conn.committed


def test_register_rejects_short_password_before_connecting(monkeypatch):
    def fail(**kwargs):
        raise AssertionError("short password should not reach the database")

    monkeypatch.setattr("pymssql.connect", fail)
    result = asyncio.run(
        auth.register(_request("127.0.0.11"), "2026001", "测试学生", "short", "student")
    )
    assert result == {"status": "error", "message": "密码长度不能少于10位"}


def test_api_login_upgrades_legacy_password(monkeypatch):
    login_cursor = _Cursor(
        {
            "id": 7,
            "student_id": "2026001",
            "username": "测试学生",
            "password": "password123",
            "role": "student",
            "created_at": None,
        }
    )
    upgrade_cursor = _Cursor()
    connections = [_Conn(login_cursor), _Conn(upgrade_cursor)]
    monkeypatch.setattr(auth, "_connect_db", lambda: connections.pop(0))
    monkeypatch.setattr(auth, "SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(
        auth,
        "create_session",
        lambda *args, **kwargs: (
            "token",
            SimpleNamespace(id=1, device_id="device", expires_at=None),
        ),
    )

    request = _request("198.51.100.20")
    result = asyncio.run(auth.api_login(request, "2026001", "password123", "device"))

    assert result["status"] == "success"
    assert not connections
    assert upgrade_cursor.calls
    _, params = upgrade_cursor.calls[0]
    assert verify_password("password123", params[0])
    assert not is_legacy_password(params[0])


def test_api_login_hashed_password_does_not_upgrade(monkeypatch):
    stored = hash_password("password123")
    login_cursor = _Cursor(
        {
            "id": 7,
            "student_id": "2026001",
            "username": "测试学生",
            "password": stored,
            "role": "student",
            "created_at": None,
        }
    )
    connect_calls = []

    def connect():
        connect_calls.append(1)
        return _Conn(login_cursor)

    monkeypatch.setattr(auth, "_connect_db", connect)
    monkeypatch.setattr(auth, "SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(
        auth,
        "create_session",
        lambda *args, **kwargs: (
            "token",
            SimpleNamespace(id=1, device_id="device", expires_at=None),
        ),
    )

    request = _request("198.51.100.20")
    result = asyncio.run(auth.api_login(request, "2026001", "password123", "device"))

    assert result["status"] == "success"
    assert len(connect_calls) == 1
    assert all("UPDATE users SET password" not in sql for sql, _ in login_cursor.calls)


def test_sliding_window_limiter(monkeypatch):
    from app.services import rate_limit

    clock = [0.0]
    monkeypatch.setattr(rate_limit.time, "monotonic", lambda: clock[0])
    limiter = rate_limit.SlidingWindowLimiter(limit=2, window_seconds=10)

    assert limiter.allow("k")
    assert limiter.allow("k")
    assert not limiter.allow("k")
    clock[0] = 11
    assert limiter.allow("k")


def test_login_rate_limit(monkeypatch):
    monkeypatch.setattr(auth, "_connect_db", lambda: _Conn(_Cursor(None)))
    request = _request("198.51.100.31")

    for _ in range(10):
        result = asyncio.run(auth.api_login(request, "2026888", "wrongpass", "device"))
        assert result["message"] == "学号或密码错误"

    blocked = asyncio.run(auth.api_login(request, "2026888", "wrongpass", "device"))
    assert blocked == {"status": "error", "message": "尝试过于频繁，请稍后再试"}


def test_register_rate_limit(monkeypatch):
    monkeypatch.setattr("pymssql.connect", lambda **kwargs: _Conn(_Cursor()))
    request = _request("198.51.100.32")

    for index in range(5):
        result = asyncio.run(
            auth.register(request, f"20269{index:02d}", "测试学生", "Password123", "student")
        )
        assert result["status"] == "success"

    blocked = asyncio.run(auth.register(request, "2026999", "测试学生", "Password123", "student"))
    assert blocked == {"status": "error", "message": "注册尝试过于频繁，请稍后再试"}
