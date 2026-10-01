"""本地测试库可用性探针。

目的：判定「把 DATABASE_URL 指向本地 sqlite」这条路是否真的走得通。

背景
----
`app/core/database.py` 的 `create_engine(...)` 无条件传入：

    connect_args={'timeout': 10, 'login_timeout': 10}

其中 `login_timeout` 是 **pymssql 专有参数**。当 URL 是 sqlite 时，这两个参数
会被原样转交给 `sqlite3.connect()`，预期抛出 TypeError。

这一点直接关系到两处已写下的结论：

1. 管理报告「故障二」称：`.env` 缺失时服务静默回退到 sqlite 并「正常启动，
   只是读写空库」。**若本测试失败，则回退路径实际上是崩溃而非静默**，
   报告措辞需要订正。
2. 冒烟基线计划以「本地按 ORM 建库」为基础。
   **若 sqlite 不可用，该计划需要另找方案。**

这两个问题在此前均是**推断**，本文件用于把它变成实测事实。
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 阶段 3.2：`Base` 从 `database` 移到了 `app.models`。此前 `import database`
# 一条语句就顺带把全部模型注册进 metadata；现在这一步必须显式发生，
# 否则 create_all 会建出一张表都不少的**空** schema——不报错，只是什么都没建。
from app.models import Base  # noqa: E402


def _reimport_database(monkeypatch, db_file: Path):
    """在 DATABASE_URL 指向本地 sqlite 的前提下重新导入 database 模块。

    必须在导入前设置环境变量：config._load_dotenv() 使用 os.environ.setdefault，
    因此预先存在的环境变量优先于 .env，从而无需改动 .env 即可切换数据库。

    **调用方必须同时请求 `module_surgery` 夹具**——本函数会摘掉 `database` 与
    `config`，不复原就会污染后续测试（详见 conftest 中该夹具的说明）。
    """
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")
    for mod in ("app.core.database", "app.core.config"):
        sys.modules.pop(mod, None)
    from app.core import database  # noqa: PLC0415  —— 需在环境变量就位后导入

    return database


def test_local_sqlite_engine_can_connect(tmp_path, monkeypatch, module_surgery):
    """期望：DATABASE_URL 指向本地 sqlite 时，engine 可以建立连接。"""
    db_file = tmp_path / "app.db"
    database = _reimport_database(monkeypatch, db_file)

    with database.engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT 1").scalar() == 1


def test_local_sqlite_schema_can_be_created(tmp_path, monkeypatch, module_surgery):
    """期望：ORM 定义能在本地 sqlite 上建出全部表。

    用于暴露 MSSQL 专有类型（如 NVARCHAR）在 sqlite 上的兼容性问题。
    """
    db_file = tmp_path / "app.db"
    database = _reimport_database(monkeypatch, db_file)

    Base.metadata.create_all(database.engine)

    from sqlalchemy import inspect

    tables = set(inspect(database.engine).get_table_names())
    assert tables, "建表后不应为空"
    assert tables == set(Base.metadata.tables), (
        f"建出的表与 ORM 定义不一致：缺 {set(Base.metadata.tables) - tables}"
    )
