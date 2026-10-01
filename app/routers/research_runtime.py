"""研究增强运行时的配置路由。

本组共 3 条：读取当前配置、改写配置并持久化、准备模型目录骨架。
它只跟 `app.core.config` 的配置层与 `app.services.research_runtime` 打交道，
不碰数据库、不碰 WebSocket。

`_as_bool` 与 `_reset_research_runtime_state` 是本域私有，只被本组的三个处理器使用。

注意 `persist_research_runtime_config` 会**就地改写活动 env 文件**
（见 `app.core.config.ACTIVE_ENV_FILE`）——这是本组唯一有外部副作用的操作。
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

def _as_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _reset_research_runtime_state() -> None:
    try:
        research_runtime._adapters = None
        if hasattr(research_runtime, "_fusion"):
            research_runtime._fusion = None
    except Exception:
        pass


@router.get("/api/research-runtime")
async def get_research_runtime():
    try:
        ensure_research_directories()
        return {
            "status": "success",
            "config": get_research_runtime_settings_snapshot(),
            "data": research_runtime.get_runtime_summary(),
        }
    except Exception as e:
        print(f"[ERROR] 获取增强运行时状态失败: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/api/research-runtime/config")
async def update_research_runtime_config(
    deployment_profile: str = Form(...),
    enabled: Optional[str] = Form(None),
    runtime_mode: Optional[str] = Form(None),
    persist: Optional[str] = Form("true"),
):
    try:
        enabled_value = _as_bool(enabled, deployment_profile.strip().lower() == "enhanced")
        persist_value = _as_bool(persist, True)
        if persist_value:
            config_snapshot = persist_research_runtime_config(
                deployment_profile=deployment_profile,
                enabled=enabled_value,
                runtime_mode=runtime_mode or "",
            )
        else:
            config_snapshot = apply_research_runtime_config(
                deployment_profile=deployment_profile,
                enabled=enabled_value,
                runtime_mode=runtime_mode or "",
            )
        ensure_research_directories()
        _reset_research_runtime_state()
        return {
            "status": "success",
            "message": "增强运行时配置已更新",
            "persisted": persist_value,
            "config": config_snapshot,
            "data": research_runtime.get_runtime_summary(),
        }
    except Exception as e:
        print(f"[ERROR] 更新增强运行时配置失败: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/api/research-runtime/prepare-layout")
async def prepare_research_runtime_layout():
    try:
        paths = ensure_research_directories()
        _reset_research_runtime_state()
        return {
            "status": "success",
            "message": "增强版模型目录结构已准备完成",
            "paths": paths,
            "config": get_research_runtime_settings_snapshot(),
            "data": research_runtime.get_runtime_summary(),
        }
    except Exception as e:
        print(f"[ERROR] 准备增强版目录结构失败: {e}")
        return {"status": "error", "message": str(e)}
