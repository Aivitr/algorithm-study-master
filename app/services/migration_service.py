"""数据库迁移 runner：按文件名顺序执行 db/migrations/*.sql。

已执行的迁移记录在 schema_migrations 表；重复执行是 no-op，文件内容变化
（checksum 不一致）直接报错，避免“悄悄改历史迁移”。
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import Column, DateTime, MetaData, String, Table, select
from sqlalchemy.engine import Engine

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"

_METADATA = MetaData()
_SCHEMA_MIGRATIONS = Table(
    "schema_migrations",
    _METADATA,
    Column("version", String(255), primary_key=True),
    Column("checksum", String(64), nullable=False),
    Column("applied_at", DateTime, nullable=False),
)


class MigrationError(RuntimeError):
    """迁移校验或执行失败。"""


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def _migration_files(migrations_dir: Path) -> List[Path]:
    return sorted(
        (path for path in migrations_dir.glob("*.sql") if path.is_file()),
        key=lambda path: path.name,
    )


def _execute_sql(engine: Engine, sql: str) -> None:
    # SQL Server 的迁移文件自带 BEGIN/COMMIT；用 autocommit 原始连接，避免
    # SQLAlchemy 再包一层事务导致嵌套事务错误。
    if engine.dialect.name == "mssql":
        raw = engine.raw_connection()
        try:
            raw.autocommit(True)
            cursor = raw.cursor()
            cursor.execute(sql)
            raw.commit()
        finally:
            raw.close()
        return
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)


def apply_migrations(
    engine: Engine,
    migrations_dir: Path | str = MIGRATIONS_DIR,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    directory = Path(migrations_dir)
    if not directory.is_dir():
        raise MigrationError(f"迁移目录不存在: {directory}")

    _METADATA.create_all(engine, tables=[_SCHEMA_MIGRATIONS])

    with engine.connect() as conn:
        applied_rows = {
            row.version: row.checksum for row in conn.execute(select(_SCHEMA_MIGRATIONS))
        }

    applied_now: List[str] = []
    pending: List[str] = []
    for path in _migration_files(directory):
        version = path.name
        sql = path.read_text(encoding="utf-8")
        checksum = _checksum(sql)

        if version in applied_rows:
            if applied_rows[version] != checksum:
                raise MigrationError(
                    f"迁移 {version} 的内容已变化（checksum 不一致），"
                    "请新增迁移文件，不要修改已执行的历史迁移"
                )
            continue

        pending.append(version)
        if dry_run:
            continue

        _execute_sql(engine, sql)
        with engine.begin() as conn:
            conn.execute(
                _SCHEMA_MIGRATIONS.insert().values(
                    version=version,
                    checksum=checksum,
                    applied_at=datetime.now(),
                )
            )
        applied_now.append(version)

    return {
        "applied": applied_now,
        "pending": pending,
        "skipped": sorted(applied_rows),
    }
