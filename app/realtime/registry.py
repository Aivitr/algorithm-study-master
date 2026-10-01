"""实时连接单例的**唯一持有者**。

`ConnectionManager` / `SignalConnectionManager` 都持有**进程内共享**的连接状态：

    manager.active              所有连接
    manager.meeting_connections {meeting_id: {username: websocket}}
    manager.vote_confirmations  {vote_id: set(username)}

这两个必须是**模块级单例**：若不同调用点各自 `ConnectionManager()` 一个实例，
连接登记在实例 A、广播从实例 B 发出，就会"有时收得到、有时收不到"且不报错。

路由模块**不能** `from server import manager`——在 `python server.py` 启动时
server.py 的模块名是 `__main__`，`server` 不在 `sys.modules` 里，那样写会让
Python 把 server.py **再执行一遍**（重复建 app、重复注册全部路由），且不报错。
详见 `app/routers/__init__.py`。

`server.py` 用 `from app.realtime.registry import manager, signal_manager`
再导出，因此两处的 `manager` 是**同一个对象**，不要另行构造。

`ASRSessionManager` 的单例（`asr_manager`）不在这里，见 `app/realtime/asr_manager.py`。
"""

from app.realtime.connection import ConnectionManager
from app.realtime.signaling import SignalConnectionManager

manager = ConnectionManager()
signal_manager = SignalConnectionManager()
