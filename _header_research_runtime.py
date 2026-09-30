"""研究增强运行时的配置路由（阶段 5 从 server.py 拆出）。

本组共 3 条：读取当前配置、改写配置并持久化、准备模型目录骨架。
它只跟 `app.core.config` 的配置层与 `app.services.research_runtime` 打交道，
不碰数据库、不碰 WebSocket——因此是拆分中依赖最少的一组。

`_as_bool` 与 `_reset_research_runtime_state` 一并搬来：经查它们只被本组的
三个处理器使用（server.py 别处无引用），属于本域私有。

注意 `persist_research_runtime_config` 会**就地改写活动 env 文件**
（见 app.core.config.ACTIVE_ENV_FILE）——这是本组唯一有外部副作用的操作。
"""

from typing import Optional

from fastapi import APIRouter, Form

from app.core.config import (
    apply_research_runtime_config,
    ensure_research_directories,
    get_research_runtime_settings_snapshot,
    persist_research_runtime_config,
)
from app.services.research_runtime import research_runtime

router = APIRouter()
