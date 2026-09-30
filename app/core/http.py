"""HTTP 层共享的小常量（阶段 5 从 server.py 迁出）。

阶段 5 把路由按业务域拆进 `app/routers/` 之后，`NO_CACHE_HEADERS` 同时被
两个模块需要（页面路由与 Agora 令牌路由）。若各自复制一份，两份迟早会分叉——
一处改了缓存策略、另一处没改，表现为"某些接口仍然吃缓存"，且不报错。
所以给它一个共同的、非 server.py 的家。

（路由模块不能从 server.py 取它：在 `python server.py` 启动时那会让 server.py
二次执行，见 `app/routers/__init__.py`。）
"""

# 禁用缓存。用于 HTML 页面与令牌类接口——它们的内容必须每次现取。
NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}
