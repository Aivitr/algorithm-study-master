"""隔离断言：证明测试进程不会碰到生产库。

对应阶段 1 的验收标准——「确认不存在任何写入生产库的路径」。
这里把它变成一条每次运行都会执行的断言，而不是一次性的人工检查。
"""

import os
import re


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

    这条断言针对的是一个具体风险：app/core/database.py 在导入时就会连接数据库
    （见 conftest.py 的说明）。因此「导入后仍指向本地」必须被显式验证，
    否则一次不小心的导入顺序变化就会把测试变成对生产的操作。
    """
    from app.core import database

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


# ---------------------------------------------------------------------------
# 绕过 ORM 的直连路径
#
# server.py:1935（/api/register）与 server.py:1985（/api/login）不使用 ORM，
# 而是直接 pymssql.connect(server=os.getenv("DB_HOST"), ...)，**完全不读
# DATABASE_URL**。仅隔离 DATABASE_URL 对这两条路由无效。
# ---------------------------------------------------------------------------

# 判据是**形状**，不是某一个具体主机名：写死生产实例标识等于把生产地址
# 连同这份测试一起提交进公开仓库，所以只按形状匹配。
#   * 阿里云 RDS 域：任何 `<实例>.rds.aliyuncs.com`；
#   * 阿里云 RDS 实例标识：`rm-` 后接一长串小写字母数字。
PRODUCTION_HOST_PATTERNS = (
    re.compile(r"rds\.aliyuncs\.com"),
    re.compile(r"\brm-[a-z0-9]{12,}\b"),
)


def test_db_star_vars_do_not_point_at_production():
    """DB_* 变量不得指向生产服务器——它们是直连路由的唯一数据源。"""
    for key in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        value = os.environ.get(key, "")
        assert not any(p.search(value) for p in PRODUCTION_HOST_PATTERNS), (
            f"{key} 仍指向生产环境：{value}"
        )
    assert os.environ["DB_HOST"] == "127.0.0.1"


def test_db_vars_are_set_not_deleted():
    """DB_* 必须被**赋值**为无害值，而不是被删除。

    这是一个容易被"修好又改坏"的点：`config._load_dotenv()` 使用
    `os.environ.setdefault`。若测试把 DB_HOST 删掉，conftest 之外任何一次
    `import config` 都会立刻从 .env 把**生产值重新填回来**，隔离随即失效
    且毫无迹象。因此这里断言的是"存在且无害"，而不是"不存在"。
    """
    for key in ("DB_HOST", "DB_PORT", "DB_USER", "DB_PASSWORD", "DB_NAME"):
        assert key in os.environ, (
            f"{key} 被删除了而非赋成无害值——setdefault 会用 .env 的生产值填回来"
        )


def test_no_production_address_reachable_from_env():
    """全面自检：进程环境里不应残留任何生产地址。"""
    leaks = []
    for key, value in os.environ.items():
        if not isinstance(value, str):
            continue
        if any(p.search(value) for p in PRODUCTION_HOST_PATTERNS):
            leaks.append(f"{key}={value}")
    assert not leaks, f"环境变量中残留生产地址：{leaks}"


def test_production_host_patterns_catch_the_production_shapes():
    """反向自检：这两条形状规则确实能抓住生产地址。

    没有这条，正则写错（比如少写了转义点）就会让上面几条断言永远通过，
    隔离悄悄失效却毫无迹象——这正是本文件一直在防的那类静默失败。
    """
    production_like = [
        "rm-abcdefghijklmnop.sqlserver.rds.aliyuncs.com",
        "rm-0123456789abcdef",
        "mssql+pymssql://user:pw@rm-abcdefghijklmnop.rds.aliyuncs.com:1433/db",
    ]
    for value in production_like:
        assert any(p.search(value) for p in PRODUCTION_HOST_PATTERNS), (
            f"没抓住这个生产形状：{value}"
        )

    harmless = ["127.0.0.1", "db", "1433", "cscl_db", "localhost"]
    for value in harmless:
        assert not any(p.search(value) for p in PRODUCTION_HOST_PATTERNS), (
            f"误报了无害值：{value}"
        )
