"""静态页面与小型静态资源路由。

    /                 首页，返回 index.html
    /pcm-processor.js 前端录音用的 AudioWorklet 脚本

两条都不是 nginx 反代前缀下的 API，但同样是冻结的 59 条接口之一
（`tests_safe/test_route_contract.py` 的"顶层路由"断言盯着它们）。

`NO_CACHE_HEADERS` 取自 `app/core/http.py`——页面内容必须每次现取，不能吃缓存。
"""

import os

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

from app.core.http import NO_CACHE_HEADERS
from app.core.paths import PROJECT_ROOT as BASE_DIR

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
async def get_index():
    with open(os.path.join(BASE_DIR, "index.html"), "r", encoding="utf-8") as f:
        return HTMLResponse(f.read(), headers=NO_CACHE_HEADERS)

@router.get("/pcm-processor.js")
async def get_pcm_processor():
    return FileResponse(os.path.join(BASE_DIR, "pcm-processor.js"), media_type="application/javascript")
