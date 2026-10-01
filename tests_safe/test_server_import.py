"""探针：能否在本地库上导入 server 模块。

这是冒烟基线的前置问题。`server.py` 在导入时会：
  - 连接数据库（并可能执行 ALTER TABLE）
  - 读取 OSS / Agora / LLM 配置
  - 初始化 voiceprint_manager、ai_core engine 等重依赖

若导入本身就会失败或触网，基线的做法需要另作打算。

**本文件不得写入生产库**：DATABASE_URL 已由 conftest.py 在导入前切断。
"""

import socket
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_can_import_server(monkeypatch):
    """期望：在本地库的前提下，server 模块可以导入成功。"""
    import server  # noqa: F401

    assert server.app is not None


def test_server_uses_local_database():
    """期望：server 导入后，其 ORM engine 仍指向本地库。"""
    from app.core import database
    import server  # noqa: F401

    url = database.SQLALCHEMY_DATABASE_URL
    assert not url.startswith("mssql"), f"server 连到了生产库：{url}"


def test_importing_server_does_not_open_network(monkeypatch, module_surgery):
    """期望：导入 server 不应建立任何对外网络连接。

    实现方式是把 socket.connect 换成会记账的桩，记录导入期间尝试连接的地址，
    再断言这些地址都是本地回环。

    注意：这只覆盖「导入期」的连接尝试。函数体内按需发起的连接需要在
    基线录制时另行阻断。
    """
    import importlib

    attempts = []

    def spy_connect(self, address, *args, **kwargs):
        attempts.append(address)
        raise OSError(f"网络访问已被测试阻断：{address}")

    monkeypatch.setattr(socket.socket, "connect", spy_connect)

    for mod in ("server", "app.core.database", "app.core.config"):
        sys.modules.pop(mod, None)

    try:
        importlib.import_module("server")
    except OSError as exc:
        pytest.fail(f"导入 server 时尝试了网络连接：{exc}")

    remote = [a for a in attempts if not _is_loopback(a)]
    assert not remote, f"导入 server 时连向了外部地址：{remote}"


def _is_loopback(address) -> bool:
    if not isinstance(address, tuple) or not address:
        return True
    host = str(address[0])
    return host in {"127.0.0.1", "::1", "localhost", "0.0.0.0"}
