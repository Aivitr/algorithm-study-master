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
# 这是**唯一**一处允许依赖 server.py 自身位置的地方——
# 除此之外所有路径解析一律走 app.core.paths。
_BOOTSTRAP_DIR = os.path.dirname(os.path.abspath(__file__))
if _BOOTSTRAP_DIR not in sys.path:
    sys.path.insert(0, _BOOTSTRAP_DIR)

from app.core.paths import PROJECT_ROOT, STORAGE_SUBDIRS, project_path

# 引导目录必须与 paths.py 解析出的仓库根一致，否则这里立刻报错。
if os.path.abspath(_BOOTSTRAP_DIR) != str(PROJECT_ROOT):
    raise RuntimeError(
        f"server.py 的所在目录（{_BOOTSTRAP_DIR}）与 paths.py 解析出的仓库根"
        f"（{PROJECT_ROOT}）不一致。\n"
        f"若确实要移动 server.py，请同步修改本文件的导入引导段——"
        f"此处失败是有意的：静默错位会让 storage/ 等数据目录指到别处。"
    )

BASE_DIR = str(PROJECT_ROOT)  # 兼容既有的 os.path.join(BASE_DIR, ...) 调用点

# 追加进 sys.path 的目录，登记下来供 tests_safe/test_paths_anchor.py 断言其存在。
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

# 实时链路管理器：两者均为纯内存结构，不碰数据库与网络。
from app.realtime.connection import ConnectionManager
from app.realtime.signaling import SignalConnectionManager

# 📦 OSS📦
# 定义在 app/core/oss.py，此处再导出。不能从 server.py 取（`python server.py`
# 下会让 server.py 二次执行）；定义只保留一份。
from app.core.oss import USE_OSS, get_oss_manager

try:
    from app.services.ai_core import engine
except ImportError:
    sys.exit(1)

# 导入声纹管理器
from app.services.voiceprint_manager import voiceprint_manager

# 路径锚点由 app.core.paths 统一解析——ROOT_DIR 与 BASE_DIR 都是它在 server.py
# 里的别名，值不随本文件的位置变化。
ROOT_DIR = BASE_DIR
for d in ("storage", *STORAGE_SUBDIRS):
    os.makedirs(os.path.join(ROOT_DIR, d), exist_ok=True)

app = FastAPI()

# 定义在 app/core/http.py，此处再导出。路由模块不能从 server.py 导入
# （`python server.py` 下会二次执行整个文件）；定义只保留一份。
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

# 前端外部依赖本地化的落点。与上面 /storage 同类：**框架级静态挂载，不计入
# 59 个接口**，但同样钉在 tests_safe/test_route_contract.py 的 FRAMEWORK_ROUTES 里。
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


# ==================== 再导出（迁移兼容面） ====================
# 下面这一整段是新模块的**再导出**，为的是不改 `import server; server.X` 的
# 对外可见性：仓库内的 tests_safe/ 与 archive/ops-scripts/ 里有这样用的地方，
# 仓库外可能也有。
#
# 哪天真要瘦身，可以整段删掉——已实测需要保留的只有 4 个：manager、
# signal_manager、ConnectionManager、SignalConnectionManager
# （tests_safe/test_websocket_and_manager.py 用）；另有 BASE_DIR、ROOT_DIR、
# _SERVER_SYSPATH_ADDITIONS、app 是 server.py 自己定义或本来就有的。
# 删之前请自行确认仓库外没有使用者。

# 🔊 analyzer🔊
# 定义在 app/realtime/emotion_helpers.py，此处再导出。
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

# 从**真实出处**再导入一次，不从 emotion_helpers 转手——避免让依赖链绕远路。
from app.core.emotions import normalize_emotion_label
from app.services.user_lookup import resolve_user_by_identifier


# 🧠 (🧠10🧠)
# 定义在 app/realtime/state.py，此处再导出。
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


# 定义在 app/realtime/speech.py，此处再导出。
from app.realtime.speech import (
    _persist_speech_emotion_artifacts,
    _create_realtime_transcript_entry,
    _run_realtime_speech_analysis,
    _stream_realtime_speech_analysis_events,
)


# 定义在 app/services/meeting_metrics.py，此处再导出。
# 这两个辅助同时被学生统计域与教师域使用，因此住在中立的服务模块里。
from app.services.meeting_metrics import (
    _build_meeting_activity_map,
    _build_meeting_window_map,
)


# 定义在 app/realtime/knowledge_graph.py，此处再导出。
from app.realtime.knowledge_graph import update_knowledge_graph


# === 🎥 📹:👥📊 (yield) ===
# 定义在 app/realtime/stream.py，此处再导出。
from app.realtime.stream import process_user_stream_generator


# ... (?? get/post login ??) ...


# === WebSocket 连接管理器 / WebRTC 信令 ===
#
# 连接管理器类定义在 app/realtime/，单例定义在 app/realtime/registry.py，
# 此处**再导出**。路由模块不能 `from server import manager`（`python server.py`
# 下会让本文件再执行一遍——重复建 app、重复注册全部 59 条路由，且不报错），
# 见 app/routers/__init__.py。
#
# 单例全局唯一：这里用 `from ... import` 再导出而非重新赋值，因此
# `server.manager` 与 `app.realtime.registry.manager` 是**同一个对象**，
# `from server import manager`（tests_safe/test_websocket_and_manager.py 的
# 隔离夹具）拿到的身份不变。
from app.realtime.registry import manager, signal_manager


# === 实时语音识别 ASR 会话管理 ===
# 定义在 app/realtime/asr_manager.py，此处再导出。
from app.realtime.asr_manager import (
    ASRSessionManager,
    asr_manager,
)


# ==================== 路由装配 ====================
# 路由按业务域放在 app/routers/，此处只做装配。
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


# 空 router：这个模块里的两个处理器**没有**装饰器，所以不贡献任何路由。
# 仍然要 include——app/routers/ 下有文件却没被装配，test_routers_layout 会报红。
# 详情见 app/routers/unrouted.py 的文件头。
from app.routers.unrouted import router as unrouted_router

app.include_router(unrouted_router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
