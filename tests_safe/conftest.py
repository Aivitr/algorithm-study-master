"""tests_safe 自己的夹具。

**生产隔离不在这里**——它在仓库根的 `conftest.py`。原先它写在本文件里，
但那只能覆盖「按默认方式运行 pytest」（`pytest.ini` 的 `testpaths = tests_safe`）；
一旦显式给出路径参数，`testpaths` 就被覆盖，本文件根本不会加载。详见根
`conftest.py` 的文件头。

本文件保留了「隔离是否已生效」的断言（见下），根 conftest 若被删除或改名，
这里会立刻失败，而不是静默地退回生产配置。
"""

import os
import sys
from pathlib import Path

import pytest

# 保证 `from fixtures import ...` 可用（不依赖 pytest 的 import 模式）
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


# --------------------------------------------------- 隔离是否已生效（防线二）
def _assert_isolation_active() -> None:
    """确认仓库根 conftest.py 已经跑过。

    这不是重复实现，而是**对根闸门的断言**：本文件只有在根 conftest 之后加载，
    若后者不存在，`.env` 的生产值就会原样留在这里——那时下面的断言会失败。
    """
    url = os.environ.get("DATABASE_URL", "")
    problems = []
    if not url.startswith("sqlite"):
        problems.append(f"DATABASE_URL 未隔离：{url or '(未设置)'}")
    if os.environ.get("DB_HOST") not in ("127.0.0.1", "localhost", "::1"):
        problems.append(f"DB_HOST 未隔离：{os.environ.get('DB_HOST') or '(未设置)'}")
    if os.environ.get("DB_PORT") != "1":
        problems.append(f"DB_PORT 未隔离：{os.environ.get('DB_PORT') or '(未设置)'}")
    assert not problems, (
        "生产隔离未生效，测试拒绝启动：\n  - "
        + "\n  - ".join(problems)
        + "\n请确认仓库根的 conftest.py 存在（它是唯一覆盖所有调用方式的闸门）。"
    )


_assert_isolation_active()


def pytest_addoption(parser):
    parser.addoption(
        "--record-baseline",
        action="store_true",
        default=False,
        help="把当前行为录制为基线，而不是与已录基线比对",
    )


# ------------------------------------------------------------------ 应用与数据


@pytest.fixture
def module_surgery():
    """允许测试临时摘换 `sys.modules` 中的模块，结束后**自动复原**。

    为什么必须有这个夹具
    --------------------
    `app/core/database.py` 在**导入期**读 `DATABASE_URL` 建 engine，而
    `app/core/config.py` 在**导入期**执行 `_load_dotenv()`（用 `setdefault`
    从 `.env` 补值）。要验证「换个 `DATABASE_URL` 会怎样」，只能把这两个模块
    从 `sys.modules` 摘掉再重新导入——没有别的办法。

    但**摘掉之后不还回去，就会污染后续每一个测试**：之后的 `import database`
    拿到的是本测试临时造的那个模块，engine 指向本测试的临时库。

    实测症状：`test_local_db.py` 摘换 `database` 后未还原，导致
    `test_route_baseline` 出现「应用连的库」与「播种写入的库」是两个不同文件
    （`smartclass-tests-*.app.db` vs `pytest-*/test_local_sqlite_schema_*/app.db`），
    基线比对报出无意义的差异。这类故障不会报错，只会静默比对错东西。
    """
    saved = dict(sys.modules)
    try:
        yield
    finally:
        for name in list(sys.modules):
            if name not in saved:
                del sys.modules[name]
            elif sys.modules[name] is not saved[name]:
                sys.modules[name] = saved[name]


@pytest.fixture(scope="session")
def local_app():
    """在本地库上建表并返回 FastAPI app。"""
    from app.core import database
    from app.models import Base

    Base.metadata.create_all(database.engine)

    import server

    return server.app


@pytest.fixture(scope="session")
def seeded_ids(local_app):
    """写入合成数据，返回固定 ID 表。"""
    from app.core import database
    from fixtures import seed_all

    db = database.SessionLocal()
    try:
        return seed_all(db)
    finally:
        db.close()


@pytest.fixture(scope="session")
def client(local_app):
    """TestClient——进程内驱动 ASGI，不监听端口、不出网。"""
    from fastapi.testclient import TestClient

    with TestClient(local_app) as c:
        yield c
