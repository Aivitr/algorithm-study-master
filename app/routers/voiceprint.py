"""声纹识别域的路由。

本模块**只从 `app.*` 导入**，不导入 `server`；依赖方向单向：
`server` → `app.routers.*`，永不反向（`from server import ...` 会让 server.py
二次执行，见 `app/routers/__init__.py`）。

共享状态从哪来
--------------
- `logger`：本模块自取（全仓库没有 logging 配置，日志名不参与输出）。
- `USE_OSS` / `get_oss_manager`：直接取自 `app.services.oss_utils`，那本就是它们的
  定义处；降级判定与 server.py 同构。
- `BASE_DIR` / `ROOT_DIR`：由 `app.core.paths.PROJECT_ROOT` 重新定义，
  与 server.py 中 `BASE_DIR = str(PROJECT_ROOT)` 取值相同。
"""

import asyncio
import logging
import os
import re
import subprocess
import time

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse

from app.core.database import SessionLocal
from app.core.paths import PROJECT_ROOT
from app.models import User
from app.services.voiceprint_manager import voiceprint_manager

try:
    from app.services.oss_utils import get_oss_manager

    USE_OSS = True
except Exception:  # OSS 未配置时降级
    USE_OSS = False

logger = logging.getLogger(__name__)

BASE_DIR = str(PROJECT_ROOT)
ROOT_DIR = BASE_DIR

router = APIRouter()


# ==================== 声纹识别 API ====================

def _voiceprint_upload_suffix(audio: UploadFile) -> str:
    filename = audio.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    allowed = {".wav", ".webm", ".ogg", ".mp3", ".m4a", ".mp4", ".aac"}
    if ext in allowed:
        return ext
    content_type = (audio.content_type or "").split(";")[0].lower()
    return {
        "audio/wav": ".wav",
        "audio/wave": ".wav",
        "audio/x-wav": ".wav",
        "audio/webm": ".webm",
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".mp4",
        "audio/aac": ".aac",
    }.get(content_type, ".webm")


def _voiceprint_temp_path(username: str, prefix: str, suffix: str) -> str:
    safe_user = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(username or "user"))
    os.makedirs(os.path.join(ROOT_DIR, "storage"), exist_ok=True)
    return os.path.join(ROOT_DIR, "storage", f"{prefix}_{safe_user}_{int(time.time() * 1000)}{suffix}")


def _prepare_voiceprint_audio(input_path: str) -> str:
    """Convert browser uploads such as WebM/Opus into a real 16k mono WAV file."""
    if os.path.splitext(input_path)[1].lower() == ".wav":
        return input_path
    output_path = os.path.splitext(input_path)[0] + "_16k.wav"
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        input_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not os.path.exists(output_path):
        detail = (result.stderr or result.stdout or "unknown ffmpeg error").strip()
        raise RuntimeError(f"音频格式转换失败: {detail[:300]}")
    return output_path

@router.get("/voiceprint_register")
async def voiceprint_register_page():
    """声纹注册页面"""
    return FileResponse(os.path.join(BASE_DIR, "voiceprint_register.html"))


@router.post("/api/voiceprint/register")
async def register_voiceprint(
    username: str = Form(...),
    audio: UploadFile = File(...)
):
    """
    注册用户声纹

    Args:
        username: 用户名
        audio: 音频文件（WAV/MP3等格式）
    """
    temp_audio_path = None
    prepared_audio_path = None
    try:
        # 保存临时音频文件
        temp_audio_path = _voiceprint_temp_path(username, "temp_voiceprint", _voiceprint_upload_suffix(audio))

        with open(temp_audio_path, "wb") as f:
            content = await audio.read()
            if not content:
                return {"status": "error", "message": "没有收到有效音频，请重新录制"}
            f.write(content)

        prepared_audio_path = await asyncio.to_thread(_prepare_voiceprint_audio, temp_audio_path)

        # 上传到OSS（如果启用）
        audio_url = None
        if False and USE_OSS:
            try:
                oss_mgr = get_oss_manager()
                audio_url = oss_mgr.upload_voiceprint(prepared_audio_path, username)
                logger.info(f"[声纹] 音频已上传到OSS: {audio_url}")
            except Exception as e:
                logger.warning(f"[声纹] OSS上传失败，使用本地文件: {e}")

        # 注册声纹：始终使用本地转换后的真实 WAV，避免 URL 下载或扩展名不匹配造成失败
        success, message = await asyncio.to_thread(
            voiceprint_manager.register_voiceprint,
            username,
            prepared_audio_path,
        )

        if success:
            # 保存到数据库
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.username == username).first()
                if user:
                    user.voiceprint_url = audio_url
                    db.commit()
                    logger.info(f"[声纹] 用户 {username} 声纹URL已保存到数据库")
            except Exception as e:
                logger.error(f"[声纹] 保存到数据库失败: {e}")
            finally:
                db.close()

        # 删除临时文件
        for path in {temp_audio_path, prepared_audio_path}:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass

        if success:
            return {"status": "success", "message": message, "audio_url": audio_url}
        else:
            return {"status": "error", "message": message}

    except Exception as e:
        logger.error(f"[API] 声纹注册失败: {e}")
        # 清理临时文件
        for path in {temp_audio_path, prepared_audio_path}:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass
        return {"status": "error", "message": f"注册失败: {str(e)}"}


@router.post("/api/voiceprint/verify")
async def verify_voiceprint(
    username: str = Form(...),
    audio: UploadFile = File(...)
):
    """
    验证用户声纹

    Args:
        username: 用户名
        audio: 音频文件
    """
    temp_audio_path = None
    prepared_audio_path = None
    try:
        # 保存临时音频文件
        temp_audio_path = _voiceprint_temp_path(username, "temp_verify", _voiceprint_upload_suffix(audio))

        with open(temp_audio_path, "wb") as f:
            content = await audio.read()
            if not content:
                return {"status": "error", "message": "没有收到有效音频，请重新录制"}
            f.write(content)

        prepared_audio_path = await asyncio.to_thread(_prepare_voiceprint_audio, temp_audio_path)

        # 验证声纹
        is_match, confidence, distance = await asyncio.to_thread(
            voiceprint_manager.verify_voiceprint,
            username,
            prepared_audio_path,
        )

        # 删除临时文件
        for path in {temp_audio_path, prepared_audio_path}:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass

        return {
            "status": "success",
            "is_match": bool(is_match),
            "confidence": float(confidence),
            "distance": float(distance)
        }

    except Exception as e:
        logger.error(f"[API] 声纹验证失败: {e}")
        for path in {temp_audio_path, prepared_audio_path}:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass
        return {"status": "error", "message": f"验证失败: {str(e)}"}


@router.get("/api/voiceprint/status/{username}")
async def check_voiceprint_status(username: str):
    """
    检查用户声纹注册状态

    Args:
        username: 用户名
    """
    try:
        is_registered = voiceprint_manager.is_registered(username)
        return {
            "status": "success",
            "registered": is_registered,
            "username": username
        }
    except Exception as e:
        logger.error(f"[API] 检查声纹状态失败: {e}")
        return {"status": "error", "message": str(e)}


@router.delete("/api/voiceprint/unregister/{username}")
async def unregister_voiceprint(username: str):
    """
    删除用户声纹

    Args:
        username: 用户名
    """
    try:
        success, message = voiceprint_manager.unregister_voiceprint(username)
        if success:
            return {"status": "success", "message": message}
        else:
            return {"status": "error", "message": message}
    except Exception as e:
        logger.error(f"[API] 删除声纹失败: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/api/voiceprint/users")
async def get_registered_users():
    """获取所有已注册声纹的用户"""
    try:
        users = voiceprint_manager.get_all_users()
        return {
            "status": "success",
            "users": users,
            "count": len(users)
        }
    except Exception as e:
        logger.error(f"[API] 获取用户列表失败: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/api/voiceprint/identify")
async def identify_speaker(audio: UploadFile = File(...)):
    """
    从所有已注册用户中识别说话人

    Args:
        audio: 音频文件
    """
    try:
        # 保存临时文件
        temp_audio_path = os.path.join(BASE_DIR, "storage", f"temp_identify_{audio.filename}")
        os.makedirs(os.path.join(BASE_DIR, "storage"), exist_ok=True)

        with open(temp_audio_path, "wb") as f:
            content = await audio.read()
            f.write(content)

        # 识别说话人
        username, confidence, distance = voiceprint_manager.identify_speaker(temp_audio_path)

        # 删除临时文件
        try:
            os.remove(temp_audio_path)
        except:
            pass

        if username:
            return {
                "status": "success",
                "identified": True,
                "username": username,
                "confidence": float(confidence),
                "distance": float(distance)
            }
        else:
            return {
                "status": "success",
                "identified": False,
                "message": "未识别到匹配用户",
                "best_confidence": float(confidence),
                "best_distance": float(distance)
            }

    except Exception as e:
        logger.error(f"[API] 声纹识别失败: {e}")
        return {"status": "error", "message": f"识别失败: {str(e)}"}
