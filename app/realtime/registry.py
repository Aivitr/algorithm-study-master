"""实时连接单例的**唯一持有者**（阶段 5 从 server.py 迁出）。

为什么单例必须只有一个家
------------------------
`ConnectionManager` / `SignalConnectionManager` 都持有**进程内共享**的连接状态：

    manager.active              所有连接
    manager.meeting_connections {meeting_id: {username: websocket}}
    manager.vote_confirmations  {vote_id: set(username)}

若不同调用点各自 `ConnectionManager()` 一个实例，故障是**完全静默**的：某条
WebSocket 连接登记在实例 A 上，而广播从实例 B 发出——表现为"有时收得到、
有时收不到"，且不报任何错。所以这两者必须是**模块级单例**。

为什么不住在 server.py
----------------------
阶段 3 起，路由开始按业务域拆入 `app/routers/`。而路由模块**不能**
`from server import manager`——在 `python server.py` 启动时 server.py 的模块名是
`__main__`，`server` 不在 `sys.modules` 里，那样写会让 Python 把 server.py
**再执行一遍**（重复建 app、重复注册全部路由），且不报错。
详见 `app/routers/__init__.py`。

于是单例需要一个既不是 server.py、又能被双方安全导入的家——就是这里。
依赖方向因此保持单向：`server` → `app.routers.*`，两者都 → `app.realtime.registry`。

身份的连续性
------------
`server.py` 用 `from app.realtime.registry import manager, signal_manager`
**再导出**，因此 `server.manager` 与本模块的 `manager` 是**同一个对象**：
既有的 `from server import manager`（`tests_safe/test_websocket_and_manager.py`
的隔离夹具、WebSocket 路由）拿到的仍是原来那个实例。

注意 `ASRSessionManager` 的单例（`asr_manager`）**不在这里**：它的类定义仍在
server.py 内，等 WebSocket 那一组路由拆分时一并处理。
"""

from app.realtime.connection import ConnectionManager
from app.realtime.signaling import SignalConnectionManager

manager = ConnectionManager()
signal_manager = SignalConnectionManager()
