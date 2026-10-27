"""DB_AUTO_MIGRATE 开关：关闭后不得在导入期补列。"""

from app.core import database


def test_auto_migrate_defaults_to_enabled(monkeypatch):
    monkeypatch.delenv("DB_AUTO_MIGRATE", raising=False)
    assert database._auto_migrate_enabled() is True


def test_auto_migrate_can_be_disabled(monkeypatch):
    for value in ("0", "false", "no", "off", "FALSE"):
        monkeypatch.setenv("DB_AUTO_MIGRATE", value)
        assert database._auto_migrate_enabled() is False


def test_auto_migrate_stays_enabled_for_other_values(monkeypatch):
    for value in ("1", "true", ""):
        monkeypatch.setenv("DB_AUTO_MIGRATE", value)
        assert database._auto_migrate_enabled() is True
