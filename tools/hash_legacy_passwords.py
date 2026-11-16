#!/usr/bin/env python
"""一次性把 users.password 中的明文升级为 scrypt 哈希。

默认只统计，不改库：
    APP_ENV=prod python tools/hash_legacy_passwords.py
确认后执行：
    APP_ENV=prod python tools/hash_legacy_passwords.py --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ["DB_AUTO_MIGRATE"] = "0"

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import app.core.config  # noqa: E402,F401
from app.core.database import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402
from app.services.password_service import (  # noqa: E402
    hash_password,
    is_legacy_password,
    verify_password,
)


def hash_legacy_passwords(db, *, apply: bool = False) -> dict:
    users = db.query(User).all()
    legacy = [user for user in users if is_legacy_password(user.password)]
    if apply:
        for user in legacy:
            plain = user.password
            hashed = hash_password(plain)
            if not verify_password(plain, hashed):
                raise RuntimeError(f"哈希自检失败: user_id={user.id}")
            user.password = hashed
        db.commit()
    return {
        "total": len(users),
        "legacy": len(legacy),
        "updated": len(legacy) if apply else 0,
        "applied": apply,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hash legacy plaintext passwords")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="实际写库；不加时只统计",
    )
    args = parser.parse_args(argv)

    if args.apply and os.getenv("CONFIRM_DB_BACKUP") != "1":
        print(
            "写库前请先确认 RDS 备份，然后设置 CONFIRM_DB_BACKUP=1 再执行 --apply",
            file=sys.stderr,
        )
        return 1

    db = SessionLocal()
    try:
        result = hash_legacy_passwords(db, apply=args.apply)
    except Exception as exc:
        db.rollback()
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
