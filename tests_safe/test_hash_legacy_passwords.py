from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.models.base import Base
from app.services.password_service import (
    hash_password,
    is_legacy_password,
    verify_password,
)
from tools.hash_legacy_passwords import hash_legacy_passwords


def _session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(session):
    session.add_all(
        [
            User(student_id="1", username="旧用户", password="plain-pass", role="student"),
            User(
                student_id="2",
                username="已哈希用户",
                password=hash_password("Password123"),
                role="student",
            ),
        ]
    )
    session.commit()


def test_dry_run_only_counts():
    db = _session()
    try:
        _seed(db)
        result = hash_legacy_passwords(db, apply=False)
        assert result == {"total": 2, "legacy": 1, "updated": 0, "applied": False}
        assert db.query(User).filter(User.student_id == "1").one().password == "plain-pass"
    finally:
        db.close()


def test_apply_hashes_only_legacy_and_is_idempotent():
    db = _session()
    try:
        _seed(db)
        result = hash_legacy_passwords(db, apply=True)
        assert result == {"total": 2, "legacy": 1, "updated": 1, "applied": True}

        legacy_user = db.query(User).filter(User.student_id == "1").one()
        assert not is_legacy_password(legacy_user.password)
        assert verify_password("plain-pass", legacy_user.password)
        assert verify_password(
            "Password123", db.query(User).filter(User.student_id == "2").one().password
        )

        again = hash_legacy_passwords(db, apply=True)
        assert again == {"total": 2, "legacy": 0, "updated": 0, "applied": True}
    finally:
        db.close()
