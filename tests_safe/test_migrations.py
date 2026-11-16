"""迁移 runner：顺序、幂等、checksum 与 dry-run。"""

import pytest
from sqlalchemy import create_engine, inspect, text

from app.services.migration_service import MigrationError, apply_migrations


def _make_engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path / 'migrations.db'}")


def _write(directory, name, sql):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(sql, encoding="utf-8")


def test_apply_migrations_in_order_and_idempotent(tmp_path):
    migrations = tmp_path / "migrations"
    _write(migrations, "002_insert.sql", "INSERT INTO demo(name) VALUES ('b');")
    _write(migrations, "001_create.sql", "CREATE TABLE demo(id INTEGER PRIMARY KEY, name TEXT);")
    engine = _make_engine(tmp_path)

    first = apply_migrations(engine, migrations)
    assert first["applied"] == ["001_create.sql", "002_insert.sql"]
    assert first["pending"] == ["001_create.sql", "002_insert.sql"]
    assert first["skipped"] == []

    inspector = inspect(engine)
    assert inspector.has_table("demo")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT name FROM demo")).scalar_one() == "b"

    second = apply_migrations(engine, migrations)
    assert second["applied"] == []
    assert second["pending"] == []
    assert second["skipped"] == ["001_create.sql", "002_insert.sql"]


def test_checksum_change_is_rejected(tmp_path):
    migrations = tmp_path / "migrations"
    _write(migrations, "001_create.sql", "CREATE TABLE demo(id INTEGER PRIMARY KEY);")
    engine = _make_engine(tmp_path)
    apply_migrations(engine, migrations)

    _write(migrations, "001_create.sql", "CREATE TABLE demo(id INTEGER PRIMARY KEY, name TEXT);")

    with pytest.raises(MigrationError, match="checksum"):
        apply_migrations(engine, migrations)


def test_dry_run_does_not_execute(tmp_path):
    migrations = tmp_path / "migrations"
    _write(migrations, "001_create.sql", "CREATE TABLE demo(id INTEGER PRIMARY KEY);")
    engine = _make_engine(tmp_path)

    result = apply_migrations(engine, migrations, dry_run=True)

    assert result["applied"] == []
    assert result["pending"] == ["001_create.sql"]
    assert not inspect(engine).has_table("demo")
