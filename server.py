# -*- coding: utf-8 -*-
# -*- coding: utf-8 -*-
import os
import sys
import json
import threading
import logging
from datetime import datetime, timedelta
import re
import subprocess
from difflib import SequenceMatcher
from collections import deque
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# 修复 Windows 终端中文输出
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ------------------------------------------------ 导入引导（唯一允许依赖自身位置处）
# 要导入 `app` 包，总得先有一个已知的起点。本文件住在仓库根，因此它所在的
# 目录就是仓库根，可用来把包挂上 sys.path。这是**唯一**一处允许依赖
# server.py 自身位置的地方——除此之外所有路径解析一律走 app.core.paths。
_BOOTSTRAP_DIR = os.path.dirname(os.path.abspath(__file__))
if _BOOTSTRAP_DIR not in sys.path:
    sys.path.insert(0, _BOOTSTRAP_DIR)

from app.core.paths import PROJECT_ROOT, STORAGE_SUBDIRS, project_path

# 引导目录必须与 paths.py 解析出的仓库根一致。若哪天 server.py 被移进 app/，
# 这里会立刻报错——而不是让 BASE_DIR 静默指向 app/。§3.1 的失效模式正是静默。
if os.path.abspath(_BOOTSTRAP_DIR) != str(PROJECT_ROOT):
    raise RuntimeError(
        f"server.py 的所在目录（{_BOOTSTRAP_DIR}）与 paths.py 解析出的仓库根"
        f"（{PROJECT_ROOT}）不一致。\n"
        f"若确实要移动 server.py，请同步修改本文件的导入引导段——"
        f"此处失败是有意的：静默错位会让 storage/ 等数据目录指到别处。"
    )

BASE_DIR = str(PROJECT_ROOT)  # 兼容既有的 20 余处 os.path.join(BASE_DIR, ...) 调用点

# 追加进 sys.path 的目录，登记下来供 tests_safe/test_paths_anchor.py 断言其存在。
#
# `1/`、`2/` 两条已于阶段 3 移除：
#   - `1/` 实测不含任何被导入的模块（`1/README1.md` 亦确认「未被 server.py 接线」），
#     现已归档到 archive/prototypes/legacy-1/
#   - `2/` **从未存在**，原代码无条件追加它，一直是空操作
# 保留指向已归档目录的 append，只会留下一条指向虚空的路径——静默无效，
# 正是本仓库反复出现的那类故障。移除它们不改变任何行为。
_SERVER_SYSPATH_ADDITIONS = [
    os.path.join(BASE_DIR, '_tmp_agora_token_builder'),
]
for _extra_dir in _SERVER_SYSPATH_ADDITIONS:
    if os.path.isdir(_extra_dir):
        sys.path.append(_extra_dir)

import shutil
import asyncio
import time
import wave
import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, Form, Depends, File, UploadFile, Response
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload
# 🚫 ThreadPoolExecutor🚫 yield

from app.core.database import SessionLocal, get_db
from app.models import (
    AIInsight,
    EmotionLog,
    Exercise,
    KnowledgeGraph,
    LearningReport,
    Meeting,
    MemberConnection,
    StudentAnswer,
    Transcript,
    User,
    ViewpointVote,
)
from app.services.llm_service import llm
from app.services.knowledge_graph_service import kg_service
from app.core.config import (
    apply_research_runtime_config,
    ensure_research_directories,
    get_research_runtime_settings_snapshot,
    persist_research_runtime_config,
)
from app.services.research_runtime import research_runtime

# 实时链路管理器（阶段 3 自本文件迁出，见设计文档 §4.1）。
# 两者均为纯内存结构，不碰数据库与网络，因此不牵动任何初始化顺序。
from app.realtime.connection import ConnectionManager
from app.realtime.signaling import SignalConnectionManager

# 📦 OSS📦
# 阶段 5 迁至 app/core/oss.py：拆分后 app/realtime/speech.py 与将来的 stream /
# asr_manager 都要用它，而它们不能从 server.py 取（`python server.py` 下会让
# server.py 二次执行）。定义只保留一份，避免"各模块各自探测 OSS"的分叉——
# 那种分叉不报错，只表现为某个模块在 OSS 可用时却走了不可用的分支。
from app.core.oss import USE_OSS, get_oss_manager

try:
    from app.services.ai_core import engine
except ImportError:
    sys.exit(1)

# 导入声纹管理器
from app.services.voiceprint_manager import voiceprint_manager

# 路径锚点统一：原为 os.getcwd()，从非项目根目录启动会静默错位到错误的数据目录。
# 现已由 app.core.paths 统一解析——ROOT_DIR 与 BASE_DIR 都是它在 server.py 里的
# 别名，值不再随本文件的位置变化。
ROOT_DIR = BASE_DIR
for d in ("storage", *STORAGE_SUBDIRS):
    os.makedirs(os.path.join(ROOT_DIR, d), exist_ok=True)

app = FastAPI()

# 阶段 5 迁至 app/core/http.py，此处**再导出**：拆分后的路由模块也要用它，
# 而路由模块不能从 server.py 导入（`python server.py` 下会二次执行整个文件）。
# 定义只保留一份，避免两处缓存策略分叉——那种分叉不报错，只表现为
# "某些接口仍然吃缓存"。
from app.core.http import NO_CACHE_HEADERS

# 🔧 CORS🔧
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 🌍
    allow_credentials=True,
    allow_methods=["*"],  # 🌍
    allow_headers=["*"],  # 🌍
)

app.mount("/storage", StaticFiles(directory=os.path.join(BASE_DIR, "storage")), name="storage")

# 🔊 analyzer🔊
# 阶段 5 迁至 app/realtime/emotion_helpers.py，此处**再导出**（调用点保持不变）。
from app.realtime.emotion_helpers import (
    get_analyzer,
    map_silent_emotion,
    map_speaking_emotion,
    is_speaking,
    analyze_audio_tone,
    _emotion_selection_key,
    _body_action_key,
    _detect_visual_state_from_video,
)

# 这两个原本紧跟在上面那一块里（作为"再导出点"），随搬迁一起进了
# app/realtime/emotion_helpers.py。server.py 里仍有大量调用点，所以在这里从
# **它们的真实出处**再导入一次——不是从 emotion_helpers 转手，避免依赖链绕路。
from app.core.emotions import normalize_emotion_label
from app.services.user_lookup import resolve_user_by_identifier


# 🧠 (🧠10🧠)
# 阶段 5 迁至 app/realtime/state.py，此处**再导出**（调用点保持不变）。
from app.realtime.state import (
    kg_counter,
    recent_speech_cache,
    recent_speech_cache_lock,
    recent_media_state,
    recent_media_state_lock,
    REALTIME_TEXT_SCORING_ENABLED,
    REALTIME_SPEECH_DEDUP_WINDOW_SECONDS,
    RECENT_MEDIA_STATE_TTL_SECONDS,
    SENTENCE_SPLIT_PATTERN,
    ASR_REQUIRE_VOICEPRINT_IDENTITY,
    REALTIME_ASR_VOICEPRINT_DISABLED,
    ASR_UNKNOWN_SPEAKER_LABEL,
    ASR_SPEAKER_CACHE_TTL_SECONDS,
    ASR_SPEAKER_CACHE_MAX_HITS,
    ASR_SENTENCE_END_SILENCE_SECONDS,
    ASR_SELF_VOICE_GATE_ENABLED,
    ASR_SELF_VOICE_GATE_MIN_MS,
    ASR_SELF_VOICE_GATE_WINDOW_MS,
    ASR_SELF_VOICE_GATE_CHECK_INTERVAL_MS,
    ASR_SELF_VOICE_GATE_SILENCE_MS,
    ASR_SELF_VOICE_GATE_RMS_THRESHOLD,
    ASR_SELF_VOICE_GATE_THRESHOLD,
    ASR_SELF_VOICE_GATE_FAIL_GRACE_DISTANCE,
    ASR_SELF_VOICE_GATE_FAILS_TO_CLOSE,
    _normalize_transcript_text,
    _transcript_text_similar,
    _cleanup_recent_speech_cache,
    _mark_recent_speech,
    _reserve_recent_speech_by_volume,
    _attach_recent_speech_transcript,
    _stage_recent_media_state_assets,
    _storage_relative_path,
    _remember_recent_media_state,
    _get_recent_media_state,
    _split_realtime_sentences,
)


# 阶段 5 迁至 app/realtime/speech.py，此处**再导出**（调用点保持不变）。
from app.realtime.speech import (
    _persist_speech_emotion_artifacts,
    _create_realtime_transcript_entry,
    _run_realtime_speech_analysis,
    _stream_realtime_speech_analysis_events,
)




# 阶段 5 迁至 app/services/meeting_metrics.py，此处**再导出**（server.py 内的
# 既有调用点保持不变）。这两个辅助同时被学生统计域与教师域使用，不能只跟着
# 其中一组走，因此给它们一个中立的家。
from app.services.meeting_metrics import (
    _build_meeting_activity_map,
    _build_meeting_window_map,
)



# 阶段 5 迁至 app/realtime/knowledge_graph.py，此处**再导出**（调用点保持不变）。
from app.realtime.knowledge_graph import update_knowledge_graph


# === 🎥 📹:👥📊 (yield) ===
# 阶段 5 迁至 app/realtime/stream.py，此处**再导出**（调用点保持不变）。
from app.realtime.stream import process_user_stream_generator


# ... (?? get/post login ??) ...










# === WebSocket 连接管理器 / WebRTC 信令 ===
#
# 两个类已于阶段 3 迁至 app/realtime/（设计文档 §4.1）；
# 单例本身于阶段 5 迁至 app/realtime/registry.py，此处**再导出**。
#
# 为什么不把单例留在原地：拆出去的路由模块不能 `from server import manager`
# ——在 `python server.py` 启动时 server.py 的模块名是 `__main__`，`server`
# 不在 sys.modules 里，那样写会让本文件**再执行一遍**（重复建 app、重复注册
# 全部 59 条路由），且不报错。详见 app/routers/__init__.py。
#
# 单例仍然全局唯一：这里用 `from ... import` 再导出而非重新赋值，
# 因此 `server.manager` 与 `app.realtime.registry.manager` 是**同一个对象**，
# 既有的 `from server import manager`（WebSocket 路由、
# tests_safe/test_websocket_and_manager.py 的隔离夹具）拿到的身份不变。
from app.realtime.registry import manager, signal_manager


# === 实时语音识别 ASR 会话管理 ===
# 阶段 5 迁至 app/realtime/asr_manager.py，此处**再导出**（调用点保持不变）。
from app.realtime.asr_manager import (
    ASRSessionManager,
    asr_manager,
)









async def select_viewpoint(
    meeting_id: int = Form(...),
    viewpoint_id: int = Form(...),
    viewpoint_title: str = Form(...),
    viewpoint_desc: str = Form(...),
    db: Session = Depends(get_db)
):
    """老师直接选择观点（不投票）"""
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"status": "error", "message": "课堂不存在"}

        selected_viewpoint = {
            "id": viewpoint_id,
            "title": viewpoint_title,
            "description": viewpoint_desc
        }

        # 生成子目标
        result = llm.generate_sub_goals(
            selected_viewpoint,
            meeting.topic,
            meeting.knowledge_points
        )

        # 更新教学目标
        if result.get("sub_goals"):
            new_goals = meeting.knowledge_points or []
            for sg in result["sub_goals"]:
                new_goals.append({
                    "id": len(new_goals) + 1,
                    "desc": f"[深入探讨] {sg['desc']}",
                    "status": "pending",
                    "parent_viewpoint": viewpoint_title
                })
            meeting.knowledge_points = new_goals
            db.commit()

        return {
            "status": "success",
            "sub_goals": result.get("sub_goals", []),
            "guidance": result.get("guidance", ""),
            "updated_goals": meeting.knowledge_points
        }
    except Exception as e:
        print(f"[ERROR] 选择观点失败: {e}")
        return {"status": "error", "message": str(e)}






# 新增接口: 获取快照




async def upload_report_template(
    template_file: UploadFile = File(...),
    teacher_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """??"""
    try:
        from app.models import ReportTemplate
        
        template_dir = os.path.join(BASE_DIR, "storage", "templates")
        os.makedirs(template_dir, exist_ok=True)
        
        original_filename = template_file.filename
        filename = f"template_{teacher_id}_{int(time.time())}_{original_filename}"
        filepath = os.path.join(template_dir, filename)
        
        with open(filepath, "wb") as f:
            content = await template_file.read()
            f.write(content)
        
        # ??
        template = ReportTemplate(
            teacher_id=teacher_id,
            filename=original_filename,
            filepath=filepath,
            is_default=1  # ??
        )
        
        # ??
        db.query(ReportTemplate).filter(
            ReportTemplate.teacher_id == teacher_id,
            ReportTemplate.is_default == 1
        ).update({"is_default": 0})
        
        db.add(template)
        db.commit()
        db.refresh(template)
        
        return {
            "status": "success",
            "template_id": template.id,
            "template_path": filepath,
            "filename": original_filename
        }
    except Exception as e:
        print(f"[ERROR] ??: {e}")
        return {"status": "error", "message": str(e)}






# ==================== 路由装配 ====================
# 阶段 5 起，路由按业务域拆入 app/routers/，此处只做装配。
# 新增一组路由时：先在 app/routers/ 建模块，再在这里 include。
from app.routers.voiceprint import router as voiceprint_router

app.include_router(voiceprint_router)


from app.routers.research_runtime import router as research_runtime_router

app.include_router(research_runtime_router)


from app.routers.votes import router as votes_router

app.include_router(votes_router)


from app.routers.auth import router as auth_router

app.include_router(auth_router)


from app.routers.pages import router as pages_router

app.include_router(pages_router)


from app.routers.meeting import router as meeting_router

app.include_router(meeting_router)


from app.routers.reports import router as reports_router

app.include_router(reports_router)


from app.routers.report_stream import router as report_stream_router

app.include_router(report_stream_router)


from app.routers.classroom_ops import router as classroom_ops_router

app.include_router(classroom_ops_router)


from app.routers.student_stats import router as student_stats_router

app.include_router(student_stats_router)


from app.routers.emotion_stats import router as emotion_stats_router

app.include_router(emotion_stats_router)


from app.routers.media_context import router as media_context_router

app.include_router(media_context_router)


from app.routers.pdf_report import router as pdf_report_router

app.include_router(pdf_report_router)


from app.routers.quiz import router as quiz_router

app.include_router(quiz_router)


from app.routers.teacher import router as teacher_router

app.include_router(teacher_router)


from app.routers.realtime import router as realtime_router

app.include_router(realtime_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
