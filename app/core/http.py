"""HTTP 层共享的小常量。

`NO_CACHE_HEADERS` 由页面路由与 Agora 令牌路由共同使用，只留这一份。

路由模块不能从 `server.py` 取它：在 `python server.py` 启动时那会让 server.py
二次执行（见 `app/routers/__init__.py`）。
"""

# 禁用缓存。用于 HTML 页面与令牌类接口——它们的内容必须每次现取。
NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}
