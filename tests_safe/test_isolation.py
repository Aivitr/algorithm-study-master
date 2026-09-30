"""隔离断言：证明测试进程不会碰到生产库。

对应设计文档中阶段 1 的验收标准——「确认不存在任何写入生产库的路径」。
这里把它变成一条每次运行都会执行的断言，而不是一次性的人工检查。
"""

import os


MSSQL_PREFIX = "mssql"


def test_database_url_is_not_production():
    """测试进程中 DATABASE_URL 不得指向 mssql（生产库）。"""
    url = os.environ.get("DATABASE_URL", "")
    assert url, "DATABASE_URL 未被 conftest 设置，隔离机制失效"
    assert not url.startswith(MSSQL_PREFIX), (
        f"测试进程连接了生产库，隔离已失效：{url}"
    )


def test_imported_engine_is_local():
    """导入 database 模块后，其 engine 仍指向本地库。

    这条断言针对的是一个具体风险：database.py 在导入时就会连接数据库
    （见 conftest.py 的说明）。因此「导入后仍指向本地」必须被显式验证，
    否则一次不小心的导入顺序变化就会把测试变成对生产的操作。
    """
    import database

    assert not database.SQLALCHEMY_DATABASE_URL.startswith(MSSQL_PREFIX), (
        f"database 模块连到了生产库：{database.SQLALCHEMY_DATABASE_URL}"
    )


def test_dangerous_legacy_suite_is_not_collected():
    """旧测试目录 tests/ 不得被 pytest 收集。

    tests/ 下的用例会 `from server import app`，而 server 经 .env 连生产库，
    其中约 38 处为写操作。pytest.ini 的 testpaths 白名单是唯一的防线，
    这里对它做一次回归保护。
    """
    import subprocess
    import sys
    from pathlib import Path

    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q"],
        cwd=project_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    collected = result.stdout

    assert "tests_safe" in collected or collected.strip() == "", collected
    assert "test_llm_endpoints" not in collected, (
        "收集到了会写生产库的 tests/test_llm_endpoints.py"
    )
    assert "/tests/" not in collected.replace("\\", "/"), (
        "收集到了 tests/ 下的旧用例"
    )
