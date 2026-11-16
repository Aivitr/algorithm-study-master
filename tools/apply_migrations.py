#!/usr/bin/env python
"""执行 db/migrations/*.sql。

用法：
    python tools/apply_migrations.py --dry-run
    python tools/apply_migrations.py

部署时由 deploy 脚本调用；只执行尚未记录的迁移，重复执行是 no-op。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 迁移 runner 自己管理 schema，禁止 import 期再去补列
os.environ["DB_AUTO_MIGRATE"] = "0"

from app.core.database import engine  # noqa: E402
from app.services.migration_service import (  # noqa: E402
    MIGRATIONS_DIR,
    MigrationError,
    apply_migrations,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply SQL migrations in filename order")
    parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=MIGRATIONS_DIR,
        help=f"迁移目录（默认 {MIGRATIONS_DIR}）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只列出待执行迁移")
    args = parser.parse_args(argv)

    try:
        result = apply_migrations(
            engine,
            args.migrations_dir,
            dry_run=args.dry_run,
        )
    except MigrationError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
