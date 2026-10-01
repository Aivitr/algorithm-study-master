"""OSS 可用性探测与惰性取用。

探测成功则 `USE_OSS = True` 并绑定 `get_oss_manager`，失败则 `USE_OSS = False`。
`app/realtime/` 下的几个模块都要用它，而那些模块不能从 `server.py` 取
（在 `python server.py` 下那会让 server.py 二次执行），所以定义只留这一份。

探测失败时把 `get_oss_manager` 显式绑成 `None`，而不是让它不存在：否则
`from app.core.oss import USE_OSS, get_oss_manager` 会在导入期直接 ImportError。
绑成 None 之后，调用点原有的 `if USE_OSS:` 守卫语义不变。
"""

try:
    from app.services.oss_utils import get_oss_manager
    USE_OSS = True
    print("OSS module imported")
except Exception as e:
    USE_OSS = False
    get_oss_manager = None
    print(f"OSS not configured: {e}")
