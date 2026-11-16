# -*- coding: utf-8 -*-
"""本地一键启动 444dsh（SQLite + 无 GPU/无云服务的最小可跑形态）。

做三件事，别的一概不碰：
1. 把 `tools/devshims` 插到 sys.path 最前——让缺失的重型可选依赖（resemblyzer）
   有一个明确报错的占位，导入链能过；
2. 没有 `.env` 时按 SQLite 本地库兜底（`.env` 已存在则以它为准）；
3. 用 uvicorn 起 server:app，打印访问地址与登录入口。

用法：
    .venv\\Scripts\\python.exe tools\\dev_server.py            # 127.0.0.1:8000
    .venv\\Scripts\\python.exe tools\\dev_server.py 8010       # 换端口
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHIMS = ROOT / "tools" / "devshims"

if str(SHIMS) not in sys.path:
    sys.path.insert(0, str(SHIMS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULTS = {
    "APP_ENV": "dev",
    "DATABASE_URL": "sqlite:///./storage/app.db",
    "DB_AUTO_MIGRATE": "0",
    "LLM_API_KEY": "sk-local-dummy-not-a-real-key",
    "RESEARCH_DEPLOYMENT_PROFILE": "standard",
    "RESEARCH_MODULES_ENABLED": "false",
    "RESEARCH_RUNTIME_MODE": "documented_only",
    "WATCHFILES_FORCE_POLLING": "true",
}
for key, value in DEFAULTS.items():
    os.environ.setdefault(key, value)

os.chdir(ROOT)

import uvicorn  # noqa: E402


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print(f"[444dsh] workdir = {ROOT}")
    print(f"[444dsh] db      = {os.environ['DATABASE_URL']}")
    print(f"[444dsh] open    = http://127.0.0.1:{port}/")
    uvicorn.run("server:app", host="127.0.0.1", port=port, reload=False, log_level="info")


if __name__ == "__main__":
    main()
