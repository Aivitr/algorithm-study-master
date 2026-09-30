"""OSS 可用性探测与惰性取用（阶段 5 从 server.py 迁出）。

原本是 server.py 模块级的一段 try/except：探测成功则 `USE_OSS = True` 并绑定
`get_oss_manager`，失败则 `USE_OSS = False`。阶段 5 之后，`app/realtime/speech.py`
与（将来的）`app/realtime/stream.py`、`app/realtime/asr_manager.py` 都要用它，
而这些模块**不能**从 server.py 取（在 `python server.py` 下那会让 server.py
二次执行）。若各自复制一份探测，两份迟早分叉——表现为"某个模块明明 OSS 可用
却走了不可用的分支"，且不报错。所以定义只留这一份。

与 server.py 原版的两点差别，都是为了让它能被 `from ... import` 安全取到：

  * 探测失败时把 `get_oss_manager` 显式绑成 `None`。原版让它**不存在**，那样
    `from app.core.oss import USE_OSS, get_oss_manager` 会直接 ImportError——
    三个调用方全都在导入期挂掉。绑成 None 之后，所有调用点原有的
    `if USE_OSS:` 守卫语义完全不变（`USE_OSS` 为假时本来就不会去调它）。
  * 两次 print 原样保留，启动时的输出与迁移前逐字相同。
"""

try:
    from app.services.oss_utils import get_oss_manager
    USE_OSS = True
    print("OSS module imported")
except Exception as e:
    USE_OSS = False
    get_oss_manager = None
    print(f"OSS not configured: {e}")
