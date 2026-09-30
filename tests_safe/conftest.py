"""全局隔离：保证测试进程在任何路径下都无法触达生产环境。

本文件同时封堵**两条**通向生产库的路径——这一点常被忽略：
ORM 路径只是其中一条。详见下方 §1 与 §2。

§1 ORM 路径
-----------
`database.py` 在**模块导入时**就执行 `_ensure_transcripts_columns()`
（`database.py:243`），该函数会对 `DATABASE_URL` 指向的库执行 inspect，
必要时执行 `ALTER TABLE transcripts ADD ...`。

也就是说：**`import database` 这一个动作本身，就可能在生产库上执行 DDL。**
因此隔离必须发生在**测试模块导入之前**——conftest.py 由 pytest 在收集阶段
最先加载，是唯一可靠的插入点。

§2 直连路径（绕过 ORM）
----------------------
`server.py:1935`（`/api/register`）与 `server.py:1985`（`/api/login`）
**不使用 ORM**，而是直接：

    import pymssql
    conn = pymssql.connect(server=os.getenv("DB_HOST"), ...)

它们**完全不读 `DATABASE_URL`**。因此只改 `DATABASE_URL` 对这两条路由毫无作用，
调用它们仍会真实连接到生产服务器并写入数据。

**为什么不能简单地 `del os.environ["DB_HOST"]`**：
`config._load_dotenv()` 使用 `os.environ.setdefault`，若该键不存在，
它会立刻从 `.env` 把生产值重新填回来。**必须显式赋成无害值**——键已存在时
setdefault 才不会覆盖。

§3 socket 层兜底
---------------
上述两条是"已知的"绕过路径。为防还有未发现的路径，另加一道与具体实现无关的
防护：整个测试会话期间阻断一切非回环的网络连接（见 `block_external_network`）。
这是一道兜底，不是替代品。
"""

import os
import socket
import sys
import tempfile
from pathlib import Path

import pytest

# 保证 `from fixtures import ...` 可用（不依赖 pytest 的 import 模式）
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def pytest_addoption(parser):
    parser.addoption(
        "--record-baseline",
        action="store_true",
        default=False,
        help="把当前行为录制为基线，而不是与已录基线比对",
    )

_SESSION_TMP = Path(tempfile.mkdtemp(prefix="smartclass-tests-"))

# ---------------------------------------------------------------- §1 ORM 路径
os.environ["DATABASE_URL"] = f"sqlite:///{(_SESSION_TMP / 'app.db').as_posix()}"

# ------------------------------------------------------- §2 直连 pymssql 路径
# 显式赋值（而非删除）——见文件头说明。
os.environ["DB_HOST"] = "127.0.0.1"
os.environ["DB_PORT"] = "1"  # 不可达端口
os.environ["DB_USER"] = "testsuite"
os.environ["DB_PASSWORD"] = "testsuite"
os.environ["DB_NAME"] = "testsuite"

# ------------------------------------------------------------ §3 socket 兜底
_LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0", "", None}


def _is_loopback(address) -> bool:
    if isinstance(address, str):
        return address in _LOOPBACK
    if isinstance(address, (tuple, list)) and address:
        return str(address[0]) in _LOOPBACK
    return True


@pytest.fixture(scope="session", autouse=True)
def block_external_network():
    """整个会话期间，禁止任何非回环的网络连接。

    与实现无关——即便某条路由用了我们尚未发现的第三方客户端，
    只要它试图连外网，就会在这里被拦下。
    """
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    attempts = []

    def guard(self, address, *args, **kwargs):
        if not _is_loopback(address):
            attempts.append(address)
            raise OSError(
                f"测试进程禁止访问外部网络，已阻断：{address}。"
                f"若该连接指向生产环境，即为隔离失效。"
            )
        return real_connect(self, address, *args, **kwargs)

    def guard_ex(self, address, *args, **kwargs):
        if not _is_loopback(address):
            attempts.append(address)
            raise OSError(f"测试进程禁止访问外部网络，已阻断：{address}")
        return real_connect_ex(self, address, *args, **kwargs)

    socket.socket.connect = guard
    socket.socket.connect_ex = guard_ex
    try:
        yield attempts
    finally:
        socket.socket.connect = real_connect
        socket.socket.connect_ex = real_connect_ex


@pytest.fixture(scope="session")
def session_tmp_dir() -> Path:
    return _SESSION_TMP


# ------------------------------------------------------------------ 应用与数据


@pytest.fixture(scope="session")
def local_app():
    """在本地库上建表并返回 FastAPI app。"""
    import database

    database.Base.metadata.create_all(database.engine)

    import server

    return server.app


@pytest.fixture(scope="session")
def seeded_ids(local_app):
    """写入合成数据，返回固定 ID 表。"""
    import database
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
