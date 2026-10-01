"""仓库级 pytest 闸门：**任何**一次 pytest 调用都先被隔离。

为什么这个文件必须在仓库根，而不是只在 tests_safe/
--------------------------------------------------
隔离原本只写在 `tests_safe/conftest.py` 里。它能生效，靠的是
`pytest.ini` 的 `testpaths = tests_safe`——**按默认方式**运行 pytest 时只收集
`tests_safe/`，于是那个 conftest 被加载。

但 `testpaths` 只管**默认收集范围**，显式给出的路径参数会完全覆盖它：

    pytest                                  → 加载 tests_safe/conftest.py，安全
    pytest archive/legacy-tests/tests-dir/test_api_endpoints.py
                                            → 只加载途经目录的 conftest；
                                              tests_safe/conftest.py 不在其中
                                            → .env 的生产值原样生效

`archive/legacy-tests/conftest.py` 里的 `collect_ignore` 也挡不住这种情况：
**`collect_ignore` 对显式指定的文件路径无效**——pytest 只在收集**目录**时应用
它，显式文件路径会绕过整个目录收集。

这不是推测。实测第二条命令收集到 3 个测试、耗时 3.59s，即一次真实的
`import server` → `import database`，也就是一次对生产库的 DDL 尝试
（`app/core/database.py` 的 `_ensure_transcripts_columns()` 在**导入期**执行）。

结论：闸门必须放在**无论参数怎么写都会被加载**的位置。conftest.py 的加载范围
是「从 confcutdir（默认即 rootdir）向下到测试文件所在目录」的每一层——
放在仓库根，它就覆盖所有参数组合。这就是本文件存在的理由。

隔离的三条路径
--------------
§1 ORM 路径、§2 直连 pymssql 路径、§3 socket 兜底，与
`tests_safe/conftest.py` 原先实现的一致，只是位置提前、覆盖面扩大。
逐条的理由（尤其是「为什么必须显式赋值而不能 del」）写在下面代码处。

本文件只做**环境隔离**，不放测试夹具；`tests_safe/conftest.py`
在此基础上追加它自己的夹具。
"""

import os
import socket
import tempfile
from pathlib import Path

import pytest

# 与 tests_safe/conftest.py、archive/ops-scripts/_prod_guard.py 使用同一套回环
# 判定，保持一致语义。
_LOOPBACK = {"127.0.0.1", "::1", "localhost", "0.0.0.0", "", None}

_SESSION_TMP = Path(tempfile.mkdtemp(prefix="smartclass-tests-"))

# ---------------------------------------------------------------- §1 ORM 路径
# `app/core/database.py` 在**导入期**读 `DATABASE_URL` 建 engine，随后
# `_ensure_transcripts_columns()` 可能执行
# `ALTER TABLE transcripts ADD ...`。**导入 database 这个动作本身即 DDL。**
#
# 因此改成一次性 sqlite 文件，DDL 即便发生也只落在临时目录里。
os.environ["DATABASE_URL"] = f"sqlite:///{(_SESSION_TMP / 'app.db').as_posix()}"

# ------------------------------------------------------- §2 直连 pymssql 路径
# `server.py` 的 `/api/register` 与 `/api/login` **不用 ORM**，而是直接
# `pymssql.connect(server=os.getenv("DB_HOST"), ...)`——它们**完全不读
# `DATABASE_URL`**，所以只改 §1 对这两条路由毫无作用。
#
# 也不能用 `del os.environ["DB_HOST"]`：`config._load_dotenv()` 用的是
# `os.environ.setdefault`，键不存在它会立刻从 `.env` 把生产值填回来。
# **必须显式赋成无害值**——键已存在时 setdefault 才不会覆盖。
os.environ["DB_HOST"] = "127.0.0.1"
os.environ["DB_PORT"] = "1"  # 不可达端口，连接立即失败
os.environ["DB_USER"] = "testsuite"
os.environ["DB_PASSWORD"] = "testsuite"
os.environ["DB_NAME"] = "testsuite"


# ------------------------------------------------------------ §3 socket 兜底
def _is_loopback(address) -> bool:
    if isinstance(address, str):
        return address in _LOOPBACK
    if isinstance(address, (tuple, list)) and address:
        return str(address[0]) in _LOOPBACK
    return True


@pytest.fixture(scope="session", autouse=True)
def block_external_network():
    """整个会话期间，阻断一切经 **Python socket 层**的非回环网络连接。

    这是一道**与实现无关的兜底**，不是上面两条的替代品。已知边界：
    `pymssql` 走的是自带的 C 扩展，不经过 `socket.socket.connect`，
    因此本夹具拦不住它——这正是 §1/§2 必须显式赋值的原因。
    它拦的是 requests / httpx / 各类纯 Python 客户端。
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
    """本次会话的临时目录——`DATABASE_URL` 指向其中的 sqlite 文件。"""
    return _SESSION_TMP


def pytest_report_header(config):
    """把隔离状态打进测试头部。

    这一条是给「静默失效」准备的：隔离一旦不生效，症状是**什么都没有发生**
    （没有报错、没有提示，只是连上了生产库）。把当前生效的目标显式印出来，
    失效时至少能在头部看见它变回了 .env 的值。
    """
    return (
        "生产隔离：已生效 "
        f"[DATABASE_URL -> {os.environ['DATABASE_URL']}] "
        f"[DB_HOST -> {os.environ['DB_HOST']}:{os.environ['DB_PORT']}]"
    )
