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
try:
    from app.services.oss_utils import get_oss_manager
    USE_OSS = True
    print("OSS module imported")
except Exception as e:
    USE_OSS = False
    print(f"OSS not configured: {e}")

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


def _persist_speech_emotion_artifacts(
    db: Session,
    *,
    user: User,
    meeting_id: int,
    username: str,
    timestamp: int,
    v_name: str,
    v_path: str,
    frame,
    ret: bool,
    vis_emotion: str,
    body_action: str,
) -> Dict[str, Any]:
    video_url = f"storage/video_chunks/{v_name}"
    snapshot_url = None
    snapshot_path = None

    if ret:
        s_name = f"{meeting_id}_{username}_{timestamp}.jpg"
        snapshot_path = os.path.join(ROOT_DIR, "storage", "snapshots", s_name)
        cv2.imwrite(snapshot_path, frame)
        snapshot_url = f"storage/snapshots/{s_name}"

    if USE_OSS:
        _v_path = v_path
        _user_id = user.id
        _meeting_id = meeting_id
        _snapshot_path = snapshot_path if ret else None
        _video_url = video_url
        _has_snapshot = ret

        def async_upload():
            try:
                oss_mgr = get_oss_manager()

                print("[FAST] 上传视频到OSS...")
                oss_video_url = oss_mgr.upload_video(_v_path, _user_id, _meeting_id)

                oss_snapshot_url = None
                if _has_snapshot and _snapshot_path and os.path.exists(_snapshot_path):
                    print("[FAST] 上传快照到OSS...")
                    oss_snapshot_url = oss_mgr.upload_snapshot(_snapshot_path, _user_id, _meeting_id)

                    try:
                        os.remove(_snapshot_path)
                    except Exception as e:
                        print(f"[WARN] 删除快照失败: {e}")

                db_update = SessionLocal()
                try:
                    emotion_log = db_update.query(EmotionLog).filter(
                        EmotionLog.meeting_id == _meeting_id,
                        EmotionLog.user_id == _user_id,
                        EmotionLog.video_url == _video_url
                    ).order_by(EmotionLog.id.desc()).first()

                    if emotion_log:
                        emotion_log.video_url = oss_video_url
                        if oss_snapshot_url:
                            emotion_log.snapshot_path = oss_snapshot_url
                        db_update.commit()
                        print("[OK] OSS链接已更新")
                    else:
                        print("[WARN] 未找到待更新的EmotionLog记录")
                except Exception as db_err:
                    print(f"[ERROR] 数据库更新失败: {db_err}")
                    db_update.rollback()
                finally:
                    db_update.close()

            except Exception as e:
                print(f"[ERROR] 上传到OSS失败: {e}")
                import traceback
                traceback.print_exc()

        threading.Thread(target=async_upload, daemon=True).start()

    vis_emotion = normalize_emotion_label(vis_emotion)
    emo_str = f"{vis_emotion}|{body_action}"
    if len(emo_str) > 90:
        emo_str = emo_str[:90]

    db.add(EmotionLog(
        meeting_id=meeting_id,
        user_id=user.id,
        emotion_type=emo_str,
        intensity=0.8,
        video_url=video_url,
        snapshot_path=snapshot_url
    ))
    db.commit()

    return {
        "video_url": video_url,
        "snapshot_url": snapshot_url,
        "snapshot_path": snapshot_path,
    }


def _create_realtime_transcript_entry(
    username: str,
    meeting_id: int,
    text: str,
    audio_volume: Optional[float] = None,
    asr_sentence_id: Optional[str] = None,
    asr_index: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    clean_text = str(text or "").strip()
    if not clean_text:
        return None

    dedup_decision = _reserve_recent_speech_by_volume(meeting_id, username, clean_text, audio_volume=audio_volume)
    if dedup_decision.get("skip"):
        return None

    db = SessionLocal()
    try:
        user = resolve_user_by_identifier(db, username)
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not user or not meeting:
            print(f"[WARN] 用户或课堂不存在: username={username}, meeting_id={meeting_id}")
            return None

        media_state = _get_recent_media_state(meeting_id, username)
        emotion_tag = normalize_emotion_label(media_state.get("emotion_tag", "neutral"))
        body_action = media_state.get("body_action", "static")
        audio_tone = media_state.get("audio_tone", "")
        audio_path = media_state.get("audio_path", "")
        video_path = media_state.get("video_path", "")
        snapshot_path = media_state.get("snapshot_path", "")

        manager.record_speech(meeting_id, username)
        enhanced_runtime_active = research_runtime.research_algorithms_active
        research_binding = research_runtime.build_initial_transcript_state(
            username=username,
            text=clean_text,
            emotion_tag=emotion_tag,
            body_action=body_action,
            audio_tone=audio_tone,
        )

        trans = Transcript(
            meeting_id=meeting_id,
            user_id=user.id,
            content=clean_text,
            audio_file_path=None,
            emotion_tag=emotion_tag,
            body_action=body_action,
            audio_tone=audio_tone or None,
            binding_source=research_binding.get("binding_source") if research_binding else None,
            binding_confidence=research_binding.get("binding_confidence") if research_binding else None,
            identity_review_status=research_binding.get("identity_review_status") if research_binding else None,
            identity_review_note=research_binding.get("identity_review_note") if research_binding else None,
            cross_modal_consistency=research_binding.get("cross_modal_consistency") if research_binding else None,
            timestamp=datetime.now(),
            quality_score=50,
            quality_feedback="评估中..."
        )
        trans.quality_feedback = "已断句，正在评分..."
        trans.audio_file_path = _storage_relative_path(audio_path)
        db.add(trans)
        db.commit()
        db.refresh(trans)

        if enhanced_runtime_active:
            staged_assets = research_runtime.stage_runtime_assets(
                meeting_id=meeting_id,
                transcript_id=trans.id,
                audio_path=audio_path,
                video_path=video_path,
                snapshot_path=snapshot_path,
            )
            research_binding = research_runtime.enqueue_transcript_enhancement(
                transcript_id=trans.id,
                meeting_id=meeting_id,
                user_id=user.id,
                student_id=getattr(user, "student_id", ""),
                username=username,
                text=clean_text,
                topic=meeting.topic,
                emotion_tag=emotion_tag,
                body_action=body_action,
                audio_tone=audio_tone,
                audio_path=staged_assets.get("audio_path", audio_path),
                video_path=staged_assets.get("video_path", video_path),
                snapshot_path=staged_assets.get("snapshot_path", snapshot_path),
            )

        timestamp = int(time.time() * 1000) + (trans.id % 997)
        _attach_recent_speech_transcript(meeting_id, username, clean_text, trans.id, timestamp)
        replaced = dedup_decision.get("replace") or {}
        if replaced.get("transcript_id"):
            old_trans = db.query(Transcript).filter(Transcript.id == int(replaced["transcript_id"])).first()
            if old_trans:
                db.delete(old_trans)
                db.commit()

        goals_snapshot = json.loads(json.dumps(meeting.knowledge_points or [], ensure_ascii=False))
        fast_payload = {
            "type": "new_speech_fast",
            "transcript_id": trans.id,
            "username": username,
            "text": clean_text,
            "tags": {"emotion": emotion_tag, "action": body_action},
            "timestamp": timestamp,
            "goals": goals_snapshot,
            "quality_score": 50,
            "quality_feedback": "评估中..."
        }
        if asr_sentence_id:
            fast_payload["asr_sentence_id"] = asr_sentence_id
        if asr_index is not None:
            fast_payload["asr_index"] = asr_index
        if replaced.get("transcript_id"):
            fast_payload["replaces_transcript_id"] = replaced.get("transcript_id")
            fast_payload["replaces_username"] = replaced.get("username")
            fast_payload["replaces_text"] = replaced.get("text")
            fast_payload["replaces_timestamp"] = replaced.get("timestamp")
        if audio_tone:
            fast_payload["audio_tone"] = audio_tone
        if research_binding:
            fast_payload["research_binding"] = research_binding

        fast_payload["quality_feedback"] = "已断句，正在评分..."

        return {
            "meeting_id": meeting_id,
            "transcript_id": trans.id,
            "timestamp": timestamp,
            "username": username,
            "topic": meeting.topic,
            "text": clean_text,
            "asr_sentence_id": asr_sentence_id,
            "asr_index": asr_index,
            "fast_payload": fast_payload,
            "emotion_tag": emotion_tag,
            "body_action": body_action,
            "audio_tone": audio_tone,
            "research_binding": research_binding,
            "enhanced_runtime_active": enhanced_runtime_active,
        }
    finally:
        db.close()


def _run_realtime_speech_analysis(prepared: Dict[str, Any], precomputed_combined: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    db = SessionLocal()
    try:
        meeting_id = int(prepared["meeting_id"])
        transcript_id = int(prepared["transcript_id"])
        username = prepared["username"]
        text = prepared["text"]
        timestamp = prepared["timestamp"]
        asr_sentence_id = prepared.get("asr_sentence_id")
        asr_index = prepared.get("asr_index")
        enhanced_runtime_active = bool(prepared.get("enhanced_runtime_active"))
        research_binding = prepared.get("research_binding")
        emotion_tag = prepared.get("emotion_tag", "neutral")
        body_action = prepared.get("body_action", "static")
        audio_tone = prepared.get("audio_tone", "")

        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        trans = db.query(Transcript).filter(Transcript.id == transcript_id).first()
        if not meeting or not trans:
            return []

        recents = db.query(Transcript).filter(
            Transcript.meeting_id == meeting_id,
            Transcript.id != transcript_id
        ).order_by(Transcript.id.desc()).limit(3).all()
        ctx = "\n".join([f"{t.user.username}:{t.content}" for t in recents if getattr(t, "user", None)])

        if precomputed_combined and isinstance(precomputed_combined, dict):
            print("[AI] 使用流式返回的同一份联合分析结果")
            combined = precomputed_combined
        else:
            print("[AI] 开始实时句级联合分析(评分+进度)...")
            combined = llm.analyze_speech_and_progress(
                speech_content=text,
                topic=meeting.topic,
                recent_context=ctx,
                current_goals=meeting.knowledge_points,
                student_name=username
            )

        quality_score = int(combined.get("score", 50) or 50)
        quality_feedback = combined.get("feedback", "") or "已评估"
        relevance = int(combined.get("relevance", 50) or 50)
        hint = combined.get("hint", "") or ""
        updated_goals = combined.get("updated_goals") or (meeting.knowledge_points or [])
        dimensions = combined.get("dimensions") or {"relevance": 50, "depth": 50, "creativity": 50, "expression": 50}
        quality_distribution = {"relevance": 0.25, "depth": 0.25, "creativity": 0.25, "expression": 0.25}
        quality_research = {}

        events: List[Dict[str, Any]] = []

        if updated_goals:
            old_done = {g["id"] for g in (meeting.knowledge_points or []) if g.get("status") == "done"}
            new_done = {g["id"] for g in updated_goals if g.get("status") == "done"}
            newly_completed = new_done - old_done
            meeting.knowledge_points = updated_goals

            if newly_completed:
                completed_descs = [g["desc"] for g in updated_goals if g["id"] in newly_completed]
                all_done = all(g.get("status") == "done" for g in updated_goals)
                events.append({
                    "type": "goal_completed",
                    "completed_goals": completed_descs,
                    "all_done": all_done,
                    "goals": updated_goals
                })

        if enhanced_runtime_active:
            pdl_result = research_runtime.refine_speech_assessment(
                text=text,
                topic=meeting.topic,
                dimensions=dimensions,
                quality_score=quality_score,
                quality_feedback=quality_feedback,
                relevance=relevance,
                emotion_tag=emotion_tag,
                body_action=body_action,
                audio_tone=audio_tone,
            )
            if pdl_result and isinstance(pdl_result, dict):
                quality_score = pdl_result.get("score", quality_score)
                quality_feedback = pdl_result.get("quality_feedback", quality_feedback)
                dimensions = pdl_result.get("dimensions", dimensions)
                quality_distribution = pdl_result.get("soft_distribution", quality_distribution)
                quality_research = pdl_result.get("research", quality_research)

        trans.relevance_score = relevance
        trans.quality_score = quality_score
        trans.quality_feedback = quality_feedback
        db.commit()

        if hint:
            db.add(AIInsight(
                meeting_id=meeting_id,
                target_user=username,
                content=hint,
                type="hint"
            ))
            db.commit()

        analysis_payload = {
            "type": "speech_analysis_update",
            "transcript_id": transcript_id,
            "username": username,
            "text": text,
            "timestamp": timestamp,
            "relevance": relevance,
            "quality_score": quality_score,
            "quality_feedback": quality_feedback,
            "quality_dimensions": dimensions,
            "goals": meeting.knowledge_points,
            "hint": hint,
            "asr_sentence_id": asr_sentence_id,
            "asr_index": asr_index
        }
        if enhanced_runtime_active:
            analysis_payload["research_binding"] = research_runtime.get_transcript_review(trans.id) or research_binding
            analysis_payload["quality_distribution"] = quality_distribution
            analysis_payload["quality_research"] = quality_research
        events.append(analysis_payload)

        transcript_count = db.query(Transcript).filter(
            Transcript.meeting_id == meeting_id
        ).count()

        if transcript_count > 0 and transcript_count % 10 == 0:
            print(f"[BOOK] 触发材料推荐: {transcript_count}条发言")
            try:
                recent_5 = db.query(Transcript).filter(
                    Transcript.meeting_id == meeting_id
                ).order_by(Transcript.id.desc()).limit(5).all()

                if len(recent_5) >= 3:
                    discussion_ctx = [{
                        "username": t.user.username,
                        "content": t.content
                    } for t in reversed(recent_5) if getattr(t, "user", None)]

                    materials_result = llm.recommend_materials(discussion_ctx, meeting.topic)

                    if materials_result.get("materials"):
                        events.append({
                            "type": "material_recommendation",
                            "materials": materials_result["materials"],
                            "trigger_reason": materials_result.get("trigger_reason", "")
                        })
            except Exception as e:
                print(f"[ERROR] 材料推荐失败: {e}")

        kg_counter[meeting_id] = kg_counter.get(meeting_id, 0) + 1
        if kg_counter[meeting_id] % 10 == 0:
            print("[WEB] 更新知识图谱...")
            updated_graph = update_knowledge_graph(meeting_id, db)
            if updated_graph:
                viz_data = kg_service.generate_graph_visualization_data(updated_graph)
                events.append({
                    "type": "knowledge_graph_update",
                    "data": viz_data
                })

        return events
    except Exception as e:
        print(f"[ERROR] 实时评分失败: {e}")
        import traceback
        traceback.print_exc()
        return []
    finally:
        db.close()


def _stream_realtime_speech_analysis_events(prepared: Dict[str, Any]):
    """Stream the real LLM feedback from the same detailed JSON analysis request."""
    db = SessionLocal()
    combined = None
    try:
        meeting_id = int(prepared["meeting_id"])
        transcript_id = int(prepared["transcript_id"])
        username = prepared["username"]
        text = prepared["text"]
        timestamp = prepared["timestamp"]
        asr_sentence_id = prepared.get("asr_sentence_id")
        asr_index = prepared.get("asr_index")

        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            yield {"__combined": None}
            return

        recents = db.query(Transcript).filter(
            Transcript.meeting_id == meeting_id,
            Transcript.id != transcript_id
        ).order_by(Transcript.id.desc()).limit(3).all()
        ctx = "\n".join([f"{t.user.username}:{t.content}" for t in recents if getattr(t, "user", None)])

        yield {
            "type": "speech_feedback_stream_start",
            "transcript_id": transcript_id,
            "username": username,
            "text": text,
            "timestamp": timestamp,
            "quality_feedback": "",
            "asr_sentence_id": asr_sentence_id,
            "asr_index": asr_index,
        }

        for item in llm.stream_speech_analysis_and_progress(
            speech_content=text,
            topic=meeting.topic,
            recent_context=ctx,
            current_goals=meeting.knowledge_points,
            student_name=username,
        ) or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "feedback_delta":
                delta = item.get("delta") or ""
                if delta:
                    yield {
                        "type": "speech_feedback_delta",
                        "transcript_id": transcript_id,
                        "username": username,
                        "text": text,
                        "timestamp": timestamp,
                        "delta": delta,
                        "asr_sentence_id": asr_sentence_id,
                        "asr_index": asr_index,
                    }
            elif item.get("type") == "result":
                combined = item.get("result")
    except Exception as e:
        print(f"[AI] 流式真实评语失败: {e}")
    finally:
        db.close()
        yield {"__combined": combined}




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
def process_user_stream_generator(username, video_data, meeting_id):
    import time
    db = SessionLocal()
    v_path = None
    a_path = None

    try:
        timestamp = int(time.time() * 1000)
        v_name = f"{meeting_id}_{username}_{timestamp}.webm"
        v_path = os.path.join(ROOT_DIR, "storage", "video_chunks", v_name)
        with open(v_path, "wb") as f:
            f.write(video_data)

        # 防御：过小/不完整的 webm 切片会导致 ffmpeg 报 EBML/EOF 错误，直接跳过
        try:
            if os.path.getsize(v_path) < 1024:  # 1KB 以下基本无有效媒体数据
                print(f"[WARN] 视频切片过小，跳过: {v_name}")
                return
        except Exception:
            pass

        a_name = f"{meeting_id}_{username}_{timestamp}.wav"
        a_path = os.path.join(ROOT_DIR, "storage", "audio_chunks", a_name)
        # 用 subprocess 检查 ffmpeg 是否成功
        try:
            proc = subprocess.run(
                ["ffmpeg", "-y", "-i", v_path, "-ac", "1", "-ar", "16000", "-f", "wav", "-loglevel", "error", a_path],
                capture_output=True,
                text=True
            )
            if proc.returncode != 0 or (not os.path.exists(a_path)) or os.path.getsize(a_path) == 0:
                err = (proc.stderr or proc.stdout or "").strip()
                print(f"[WARN] ffmpeg 转码失败，跳过该切片: {v_name} | {err[:200]}")
                return
        except Exception as e:
            print(f"[WARN] ffmpeg 执行异常，跳过该切片: {v_name} | {e}")
            return

        user = resolve_user_by_identifier(db, username)
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not user or not meeting:
            print(f"[WARN] 用户或课堂不存在: username={username}, meeting_id={meeting_id}")
            return

        ret, frame, vis_emotion, emotion_confidence, body_action = _detect_visual_state_from_video(v_path)

        vad_check = is_speaking(a_path)

        if vad_check:
            print(f"[MIC] [{username}] 检测到说话")

            _, tone = analyze_audio_tone(a_path)
            vis_emotion = map_speaking_emotion(vis_emotion, tone)

            yield {
                "type": "speaking_status",
                "username": username,
                "status": "recognizing",
                "tags": {"emotion": vis_emotion, "action": body_action}
            }

            # 语音识别。实时 ASR 会晚一点返回 final 文本，所以先把本轮音频/视频证据暂存起来，
            # 后续创建 Transcript 时再用于音色相似度、声纹聚类和身份绑定复核。
            if REALTIME_TEXT_SCORING_ENABLED:
                has_active_realtime_asr = False
                try:
                    has_active_realtime_asr = bool(
                        globals().get("asr_manager")
                        and getattr(globals().get("asr_manager"), "sessions", {}).get((meeting_id, username))
                    )
                except Exception:
                    has_active_realtime_asr = False

                artifacts = _persist_speech_emotion_artifacts(
                    db,
                    user=user,
                    meeting_id=meeting_id,
                    username=username,
                    timestamp=timestamp,
                    v_name=v_name,
                    v_path=v_path,
                    frame=frame,
                    ret=ret,
                    vis_emotion=vis_emotion,
                    body_action=body_action,
                )
                staged_recent_assets = _stage_recent_media_state_assets(
                    meeting_id,
                    username,
                    timestamp,
                    audio_path=a_path,
                    video_path=v_path,
                    snapshot_path=artifacts.get("snapshot_path", ""),
                )
                _remember_recent_media_state(
                    meeting_id,
                    username,
                    vis_emotion,
                    body_action,
                    tone,
                    audio_path=staged_recent_assets.get("audio_path", a_path),
                    video_path=staged_recent_assets.get("video_path", v_path),
                    snapshot_path=staged_recent_assets.get("snapshot_path", artifacts.get("snapshot_path", "")),
                    video_url=artifacts.get("video_url", ""),
                    snapshot_url=artifacts.get("snapshot_url", ""),
                )
                if ASR_SELF_VOICE_GATE_ENABLED and not REALTIME_ASR_VOICEPRINT_DISABLED:
                    return
                if has_active_realtime_asr:
                    return
                print(f"[FALLBACK] ASR会话不可用，回退到切片转写: meeting={meeting_id}, user={username}")
            else:
                _remember_recent_media_state(
                    meeting_id,
                    username,
                    vis_emotion,
                    body_action,
                    tone,
                    audio_path=a_path,
                    video_path=v_path,
                )

            text = None
            try:
                start_time = time.time()
                text = engine.transcribe_audio(a_path)
                elapsed = time.time() - start_time

                if text:
                    print(f"[OK] 识别成功 {elapsed:.2f}秒")
                else:
                    print(f"[WARN] 识别为空 {elapsed:.2f}秒")
            except Exception as e:
                print(f"[ERROR] [{username}] 识别失败: {e}")
                import traceback
                traceback.print_exc()
                text = None

            if text:
                normalized_text = re.sub(r'\s+', '', str(text or '').strip())
                recent_key = (int(meeting_id), normalized_text)
                now_ts = time.time()
                with recent_speech_cache_lock:
                    cached = recent_speech_cache.get(recent_key)
                    if cached and (now_ts - cached.get("ts", 0)) < 3.0:
                        cached_user = cached.get("username", "")
                        if cached_user != username:
                            print(f"[DEDUP] 同时窗内重复转写，保留首个端: meeting={meeting_id}, first={cached_user}, skip={username}")
                        else:
                            print(f"[DEDUP] 跳过同端重复转写: meeting={meeting_id}, user={username}")
                        return
                    recent_speech_cache[recent_key] = {"username": username, "ts": now_ts}

                print(f"[NOTE] 发言内容: {text} ([FAST] 快速返回...)")
                manager.record_speech(meeting_id, username)
                enhanced_runtime_active = research_runtime.research_algorithms_active
                research_binding = None

                # 第一次快速返回
                fast_payload = {
                    "type": "new_speech_fast",
                    "username": username,
                    "text": text,
                    "tags": {"emotion": vis_emotion, "action": body_action},
                    "timestamp": timestamp,
                    "goals": meeting.knowledge_points,
                    "quality_score": 50,
                    "quality_feedback": "评估中..."
                }
                if enhanced_runtime_active:
                    research_binding = research_runtime.build_initial_transcript_state(
                        username=username,
                        text=text,
                        emotion_tag=vis_emotion,
                        body_action=body_action,
                        audio_tone=tone,
                    )
                    fast_payload["audio_tone"] = tone
                    fast_payload["research_binding"] = research_binding
                yield fast_payload

                # 异步OSS上传
                video_url = f"storage/video_chunks/{v_name}"
                snapshot_url = None
                snapshot_path = None

                if ret:
                    s_name = f"{meeting_id}_{username}_{timestamp}.jpg"
                    snapshot_path = os.path.join(ROOT_DIR, "storage", "snapshots", s_name)
                    cv2.imwrite(snapshot_path, frame)
                    snapshot_url = f"storage/snapshots/{s_name}"

                if USE_OSS:
                    _v_path = v_path
                    _user_id = user.id
                    _meeting_id = meeting_id
                    _snapshot_path = snapshot_path if ret else None
                    _video_url = video_url
                    _has_snapshot = ret

                    def async_upload():
                        try:
                            oss_mgr = get_oss_manager()

                            print(f"[FAST] 上传视频到OSS...")
                            oss_video_url = oss_mgr.upload_video(_v_path, _user_id, _meeting_id)

                            oss_snapshot_url = None
                            if _has_snapshot and _snapshot_path and os.path.exists(_snapshot_path):
                                print(f"[FAST] 上传快照到OSS...")
                                oss_snapshot_url = oss_mgr.upload_snapshot(_snapshot_path, _user_id, _meeting_id)

                                try:
                                    os.remove(_snapshot_path)
                                    print(f"已删除本地快照: {_snapshot_path}")
                                except Exception as e:
                                    print(f"[WARN] 删除快照失败: {e}")

                            db_update = SessionLocal()
                            try:
                                emotion_log = db_update.query(EmotionLog).filter(
                                    EmotionLog.meeting_id == _meeting_id,
                                    EmotionLog.user_id == _user_id,
                                    EmotionLog.video_url == _video_url
                                ).order_by(EmotionLog.id.desc()).first()

                                if emotion_log:
                                    emotion_log.video_url = oss_video_url
                                    if oss_snapshot_url:
                                        emotion_log.snapshot_path = oss_snapshot_url
                                    db_update.commit()
                                    print(f"[OK] OSS链接已更新")
                                else:
                                    print(f"[WARN] 未找到待更新的EmotionLog记录")
                            except Exception as db_err:
                                print(f"[ERROR] 数据库更新失败: {db_err}")
                                db_update.rollback()
                            finally:
                                db_update.close()

                        except Exception as e:
                            print(f"[ERROR] 上传到OSS失败: {e}")
                            import traceback
                            traceback.print_exc()

                    threading.Thread(target=async_upload, daemon=True).start()

                # 保存情绪日志
                vis_emotion = normalize_emotion_label(vis_emotion)
                emo_str = f"{vis_emotion}|{body_action}"
                if len(emo_str) > 90:
                    emo_str = emo_str[:90]

                db.add(EmotionLog(
                    meeting_id=meeting_id,
                    user_id=user.id,
                    emotion_type=emo_str,
                    intensity=0.8,
                    video_url=video_url,
                    snapshot_path=snapshot_url
                ))
                db.commit()

                # 保存转录（先用占位评分）
                trans = Transcript(
                    meeting_id=meeting_id,
                    user_id=user.id,
                    content=text,
                    audio_file_path=f"storage/audio_chunks/{a_name}",
                    emotion_tag=vis_emotion,
                    body_action=body_action,
                    audio_tone=tone if enhanced_runtime_active else None,
                    binding_source=research_binding.get("binding_source") if research_binding else None,
                    binding_confidence=research_binding.get("binding_confidence") if research_binding else None,
                    identity_review_status=research_binding.get("identity_review_status") if research_binding else None,
                    identity_review_note=research_binding.get("identity_review_note") if research_binding else None,
                    cross_modal_consistency=research_binding.get("cross_modal_consistency") if research_binding else None,
                    timestamp=datetime.now(),
                    quality_score=50,
                    quality_feedback="评估中..."
                )
                db.add(trans)
                db.commit()
                if enhanced_runtime_active:
                    db.refresh(trans)

                    staged_assets = research_runtime.stage_runtime_assets(
                        meeting_id=meeting_id,
                        transcript_id=trans.id,
                        audio_path=a_path,
                        video_path=v_path,
                        snapshot_path=snapshot_path,
                    )

                    research_runtime.enqueue_transcript_enhancement(
                        transcript_id=trans.id,
                        meeting_id=meeting_id,
                        user_id=user.id,
                        student_id=getattr(user, "student_id", ""),
                        username=username,
                        text=text,
                        topic=meeting.topic,
                        emotion_tag=vis_emotion,
                        body_action=body_action,
                        audio_tone=tone,
                        audio_path=staged_assets.get("audio_path", ""),
                        video_path=staged_assets.get("video_path", ""),
                        snapshot_path=staged_assets.get("snapshot_path", ""),
                    )

                # 联合AI分析（替代原来的两次调用）
                relevance = 0
                hint = ""
                updated_goals = None
                quality_score = 50
                quality_feedback = ""
                dimensions = {"relevance": 50, "depth": 50, "creativity": 50, "expression": 50}
                quality_distribution = {"relevance": 0.25, "depth": 0.25, "creativity": 0.25, "expression": 0.25}
                quality_research = {}

                # 低信息量短句不触发LLM，直接给默认评价
                if len((text or "").strip()) >= 8:
                    try:
                        recents = db.query(Transcript).filter(
                            Transcript.meeting_id == meeting_id
                        ).order_by(Transcript.id.desc()).limit(3).all()
                        ctx = "\n".join([f"{t.user.username}:{t.content}" for t in recents])

                        print("[AI] 开始联合分析(评分+进度)...")

                        combined = llm.analyze_speech_and_progress(
                            speech_content=text,
                            topic=meeting.topic,
                            recent_context=ctx,
                            current_goals=meeting.knowledge_points,
                            student_name=username
                        )

                        if combined and isinstance(combined, dict):
                            quality_score = combined.get("score", 50)
                            quality_feedback = combined.get("feedback", "") or "已评估"
                            relevance = combined.get("relevance", 0)
                            hint = combined.get("hint", "") or ""
                            updated_goals = combined.get("updated_goals")
                            dimensions = combined.get("dimensions", dimensions)
                            print(f"[OK] 联合分析完成: score={quality_score}, relevance={relevance}")
                        else:
                            print(f"[WARN] 联合分析返回格式异常: {combined}")
                            quality_feedback = "已评估"

                    except Exception as e:
                        print(f"[ERROR] 联合AI分析失败: {e}")
                        import traceback
                        traceback.print_exc()
                        quality_feedback = "评估超时"
                else:
                    # 短句直接给默认反馈
                    quality_score = 35
                    quality_feedback = "语句较短，建议展开详细论述"

                # 更新数据库
                if updated_goals:
                    # 检测新完成的目标
                    old_done = {g["id"] for g in (meeting.knowledge_points or []) if g.get("status") == "done"}
                    new_done = {g["id"] for g in updated_goals if g.get("status") == "done"}
                    newly_completed = new_done - old_done
                    meeting.knowledge_points = updated_goals

                    # 如果有新完成的目标，发送目标完成通知
                    if newly_completed:
                        completed_descs = [g["desc"] for g in updated_goals if g["id"] in newly_completed]
                        all_done = all(g.get("status") == "done" for g in updated_goals)
                        yield {
                            "type": "goal_completed",
                            "completed_goals": completed_descs,
                            "all_done": all_done,
                            "goals": updated_goals
                        }
                if enhanced_runtime_active:
                    pdl_result = research_runtime.refine_speech_assessment(
                        text=text,
                        topic=meeting.topic,
                        dimensions=dimensions,
                        quality_score=quality_score,
                        quality_feedback=quality_feedback,
                        relevance=relevance,
                        emotion_tag=vis_emotion,
                        body_action=body_action,
                        audio_tone=tone,
                    )
                    if pdl_result and isinstance(pdl_result, dict):
                        quality_score = pdl_result.get("score", quality_score)
                        quality_feedback = pdl_result.get("quality_feedback", quality_feedback)
                        dimensions = pdl_result.get("dimensions", dimensions)
                        quality_distribution = pdl_result.get("soft_distribution", quality_distribution)
                        quality_research = pdl_result.get("research", quality_research)
                trans.relevance_score = relevance
                trans.quality_score = quality_score
                trans.quality_feedback = quality_feedback
                db.commit()

                if hint:
                    db.add(AIInsight(
                        meeting_id=meeting_id,
                        target_user=username,
                        content=hint,
                        type="hint"
                    ))
                    db.commit()

                # 第二次返回：带AI分析结果
                payload = {
                    "type": "speech_analysis_update",
                    "transcript_id": trans.id,
                    "username": username,
                    "text": text,
                    "timestamp": timestamp,
                    "relevance": relevance,
                    "quality_score": quality_score,
                    "quality_feedback": quality_feedback,
                    "quality_dimensions": dimensions,
                    "goals": meeting.knowledge_points,
                    "hint": hint
                }
                if enhanced_runtime_active:
                    payload["research_binding"] = research_runtime.get_transcript_review(trans.id) or research_binding
                    payload["quality_distribution"] = quality_distribution
                    payload["quality_research"] = quality_research
                yield payload

                # 材料推荐（每10条发言）
                transcript_count = db.query(Transcript).filter(
                    Transcript.meeting_id == meeting_id
                ).count()

                if transcript_count > 0 and transcript_count % 10 == 0:
                    print(f"[BOOK] 触发材料推荐: {transcript_count}条发言")
                    try:
                        recent_5 = db.query(Transcript).filter(
                            Transcript.meeting_id == meeting_id
                        ).order_by(Transcript.id.desc()).limit(5).all()

                        if len(recent_5) >= 3:
                            discussion_ctx = [{
                                "username": t.user.username,
                                "content": t.content
                            } for t in reversed(recent_5)]

                            materials_result = llm.recommend_materials(discussion_ctx, meeting.topic)

                            if materials_result.get("materials"):
                                print(f"[BOOK] 推荐了 {len(materials_result['materials'])} 个材料")
                                yield {
                                    "type": "material_recommendation",
                                    "materials": materials_result["materials"],
                                    "trigger_reason": materials_result.get("trigger_reason", "")
                                }
                    except Exception as e:
                        print(f"[ERROR] 材料推荐失败: {e}")

                # 知识图谱更新（每10条发言）
                if meeting_id not in kg_counter:
                    kg_counter[meeting_id] = 0
                kg_counter[meeting_id] += 1

                if kg_counter[meeting_id] % 10 == 0:
                    print(f"[WEB] 更新知识图谱...")
                    updated_graph = update_knowledge_graph(meeting_id, db)
                    if updated_graph:
                        viz_data = kg_service.generate_graph_visualization_data(updated_graph)
                        yield {
                            "type": "knowledge_graph_update",
                            "data": viz_data
                        }

        else:
            silent_emotion = map_silent_emotion(vis_emotion)
            if silent_emotion != 'calm' or body_action == 'high_activity':
                snapshot_url = None

                try:
                    if ret:
                        s_name = f"{meeting_id}_{username}_{timestamp}.jpg"
                        local_snapshot_path = os.path.join(ROOT_DIR, "storage", "snapshots", s_name)
                        cv2.imwrite(local_snapshot_path, frame)

                        if USE_OSS:
                            oss_mgr = get_oss_manager()
                            print(f"[FAST] 上传快照到OSS...")
                            snapshot_url = oss_mgr.upload_snapshot(local_snapshot_path, user.id, meeting_id)

                            try:
                                os.remove(local_snapshot_path)
                            except Exception:
                                pass
                        else:
                            snapshot_url = f"storage/snapshots/{s_name}"
                except Exception as e:
                    print(f"[ERROR] 快照处理失败: {e}")
                    if ret:
                        s_name = f"{meeting_id}_{username}_{timestamp}.jpg"
                        local_snapshot_path = os.path.join(ROOT_DIR, "storage", "snapshots", s_name)
                        cv2.imwrite(local_snapshot_path, frame)
                        snapshot_url = f"storage/snapshots/{s_name}"

                emo_str = f"{silent_emotion}|{body_action}"
                if len(emo_str) > 90:
                    emo_str = emo_str[:90]

                db.add(EmotionLog(
                    meeting_id=meeting_id,
                    user_id=user.id,
                    emotion_type=emo_str,
                    intensity=0.8,
                    snapshot_path=snapshot_url
                ))
                db.commit()

                yield {
                    "type": "new_emotion",
                    "username": username,
                    "emotion": silent_emotion,
                    "action": body_action,
                    "snapshot": snapshot_url
                }

    except Exception as e:
        print(f"Error process: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 清理过期去重缓存，避免同一句话跨时段误伤后续发言
        try:
            now_ts = time.time()
            with recent_speech_cache_lock:
                expired = [k for k, v in recent_speech_cache.items() if (now_ts - v.get("ts", 0)) > 15]
                for k in expired:
                    recent_speech_cache.pop(k, None)
        except Exception:
            pass
        try:
            if v_path and os.path.exists(v_path):
                os.remove(v_path)
            if a_path and os.path.exists(a_path):
                os.remove(a_path)
        except Exception:
            pass
        db.close()


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
class ASRSessionManager:
    """
    为每个用户维护一个阿里云 NLS 实时转写会话。
    PCM 音频从前端流入，识别结果广播给课堂所有成员。
    """

    def __init__(self):
        # { (meeting_id, username): RealtimeTranscriber }
        self.sessions = {}
        self.session_websockets = {}
        # { meeting_id: { username: WebSocket } }
        self.meeting_connections = {}
        # { (meeting_id, mic_username): [{"start_ms": int, "end_ms": int, "data": bytes}, ...] }
        self.pcm_buffers = {}
        self.pcm_total_ms = {}
        # { (meeting_id, mic_username): {aliyun_speaker_id: resolved_user_identifier} }
        self.speaker_identity_cache = {}
        self.speaker_identity_meta = {}
        self.pcm_sample_rate = 16000
        self.pcm_sample_width = 2
        self.pcm_buffer_keep_ms = 45000
        self.self_voice_gate_state = {}
        # 句子级别的音量竞争：{ sentence_id: {username: rms_volume} }
        self.sentence_volume_candidates = {}
        # 句子最后活跃时间：{ sentence_id: timestamp }
        self.sentence_last_active = {}
        # 句子合并缓冲区：{ (meeting_id, username): {"text": str, "last_time": float, "timer": asyncio.Task} }
        self.sentence_merge_buffer = {}

    def _append_pcm_buffer(self, meeting_id: int, username: str, pcm_data: bytes):
        if not pcm_data:
            return
        key = (int(meeting_id), username)
        chunks = self.pcm_buffers.setdefault(key, deque())
        start_ms = self.pcm_total_ms.get(key, 0)
        duration_ms = int((len(pcm_data) / (self.pcm_sample_width * self.pcm_sample_rate)) * 1000)
        duration_ms = max(duration_ms, 1)
        end_ms = start_ms + duration_ms
        chunks.append({"start_ms": start_ms, "end_ms": end_ms, "data": bytes(pcm_data)})
        self.pcm_total_ms[key] = end_ms

        min_ms = max(0, end_ms - self.pcm_buffer_keep_ms)
        while chunks and chunks[0]["end_ms"] < min_ms:
            chunks.popleft()

    def _pcm_duration_ms(self, pcm_data: bytes) -> int:
        if not pcm_data:
            return 0
        return int((len(pcm_data) / (self.pcm_sample_width * self.pcm_sample_rate)) * 1000)

    def _pcm_rms(self, pcm_data: bytes) -> float:
        if not pcm_data:
            return 0.0
        try:
            samples = np.frombuffer(pcm_data, dtype=np.int16)
            if samples.size == 0:
                return 0.0
            return float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
        except Exception:
            return 0.0

    def _get_recent_pcm(self, key, window_ms: int) -> bytes:
        total_ms = self.pcm_total_ms.get(key, 0)
        start_ms = max(0, total_ms - int(window_ms))
        return self._extract_pcm_segment(key, start_ms, total_ms)

    def _verify_own_voice_gate_sync(self, meeting_id: int, username: str, pcm_data: bytes) -> Dict[str, Any]:
        return {"is_match": True, "reason": "realtime_voiceprint_disabled", "confidence": 1.0, "distance": 0.0}

    async def _run_self_voice_gate_check(self, meeting_id: int, username: str, key, pcm_data: bytes, check_token: int):
        return

    def _payload_number(self, payload: Dict[str, Any], names: List[str]):
        for name in names:
            if name not in payload:
                continue
            value = payload.get(name)
            if value is None or value == "":
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    def _payload_time_window_ms(self, key, payload: Dict[str, Any], text: str):
        total_ms = self.pcm_total_ms.get(key, 0)
        begin = self._payload_number(payload, [
            "begin_time", "beginTime", "start_time", "startTime",
            "sentence_begin_time", "sentenceBeginTime", "begin", "start"
        ])
        end = self._payload_number(payload, [
            "end_time", "endTime", "sentence_end_time", "sentenceEndTime",
            "time", "end"
        ])

        def normalize_ms(value):
            if value is None:
                return None
            # 部分 SDK 会给秒，阿里云 NLS 常见为毫秒；这里做温和兼容。
            if total_ms > 10000 and 0 < value < total_ms / 20:
                return int(value * 1000)
            return int(value)

        begin_ms = normalize_ms(begin)
        end_ms = normalize_ms(end)

        if begin_ms is not None and end_ms is not None and end_ms > begin_ms:
            return max(0, begin_ms - 250), min(total_ms, end_ms + 250)

        if end_ms is not None and end_ms > 0:
            estimated = max(1800, min(8000, len(str(text or "")) * 220))
            return max(0, end_ms - estimated), min(total_ms, end_ms + 250)

        estimated = max(2500, min(8000, len(str(text or "")) * 240))
        return max(0, total_ms - estimated), total_ms

    def _extract_pcm_segment(self, key, start_ms: int, end_ms: int) -> bytes:
        chunks = self.pcm_buffers.get(key)
        if not chunks or end_ms <= start_ms:
            return b""

        pieces = []
        bytes_per_ms = (self.pcm_sample_rate * self.pcm_sample_width) / 1000.0
        for chunk in list(chunks):
            chunk_start = chunk["start_ms"]
            chunk_end = chunk["end_ms"]
            if chunk_end <= start_ms:
                continue
            if chunk_start >= end_ms:
                break

            overlap_start = max(start_ms, chunk_start)
            overlap_end = min(end_ms, chunk_end)
            start_byte = int((overlap_start - chunk_start) * bytes_per_ms)
            end_byte = int((overlap_end - chunk_start) * bytes_per_ms)
            start_byte -= start_byte % self.pcm_sample_width
            end_byte -= end_byte % self.pcm_sample_width
            if end_byte > start_byte:
                pieces.append(chunk["data"][start_byte:end_byte])

        return b"".join(pieces)

    def _write_pcm_segment_wav(self, pcm_data: bytes, meeting_id: int, speaker_id: str) -> Optional[str]:
        if len(pcm_data) < self.pcm_sample_rate * self.pcm_sample_width:
            return None
        seg_dir = os.path.join(ROOT_DIR, "storage", "asr_voiceprint_segments")
        os.makedirs(seg_dir, exist_ok=True)
        safe_speaker = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(speaker_id or "spk"))
        path = os.path.join(seg_dir, f"{int(meeting_id)}_{safe_speaker}_{int(time.time() * 1000)}.wav")
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(self.pcm_sample_width)
            wf.setframerate(self.pcm_sample_rate)
            wf.writeframes(pcm_data)
        return path

    def _resolve_speaker_identity_sync(self, meeting_id: int, mic_username: str, text: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        speaker_id = (
            payload.get("speaker_id")
            or payload.get("speakerId")
            or payload.get("speaker")
            or payload.get("spk")
        )
        if REALTIME_ASR_VOICEPRINT_DISABLED:
            return {
                "username": mic_username,
                "speaker_id": str(speaker_id) if speaker_id else None,
                "source": "realtime_voiceprint_disabled",
                "confidence": None,
                "distance": None,
            }
        if not speaker_id:
            if ASR_SELF_VOICE_GATE_ENABLED and not REALTIME_ASR_VOICEPRINT_DISABLED:
                key = (int(meeting_id), mic_username)
                gate_state = self.self_voice_gate_state.get(key, {})
                sentence_index = payload.get("index")
                sentence_id = f"{int(meeting_id)}:{mic_username}:{sentence_index}" if sentence_index is not None else None
                last_pass_at = float(gate_state.get("last_pass_at") or 0)
                pass_recent = bool(last_pass_at and (time.time() - last_pass_at) <= 8.0)
                if sentence_id and gate_state.get("pending_gate_pass") and pass_recent:
                    gate_state["verified_sentence_id"] = sentence_id
                    gate_state["active_sentence_id"] = sentence_id
                    gate_state["pending_gate_pass"] = False
                    gate_state["allow_output"] = True
                sentence_verified = bool(sentence_id and gate_state.get("verified_sentence_id") == sentence_id)
                sentence_allowed = bool(
                    gate_state.get("allow_output")
                    and (
                        not sentence_id
                        or gate_state.get("active_sentence_id") == sentence_id
                        or gate_state.get("verified_sentence_id") == sentence_id
                    )
                )
                if sentence_verified or sentence_allowed:
                    return {
                        "username": mic_username,
                        "speaker_id": None,
                        "source": "self_voice_gate_start",
                        "confidence": gate_state.get("confidence"),
                        "distance": gate_state.get("distance"),
                        "window_ms": None,
                    }
                return {
                    "username": None,
                    "speaker_id": None,
                    "source": "self_voice_gate_not_passed",
                    "confidence": gate_state.get("confidence"),
                    "distance": gate_state.get("distance"),
                }

            if not ASR_REQUIRE_VOICEPRINT_IDENTITY:
                return {
                    "username": mic_username,
                    "speaker_id": None,
                    "source": "voiceprint_disabled",
                    "confidence": None,
                    "distance": None,
                }

            start_ms, end_ms = self._payload_time_window_ms((int(meeting_id), mic_username), payload, text)
            pcm_data = self._extract_pcm_segment((int(meeting_id), mic_username), start_ms, end_ms)
            wav_path = self._write_pcm_segment_wav(pcm_data, meeting_id, "no_speaker_id")
            if wav_path:
                try:
                    if ASR_SELF_VOICE_GATE_ENABLED:
                        is_match, confidence, distance = voiceprint_manager.verify_voiceprint(
                            mic_username,
                            wav_path,
                            threshold=ASR_SELF_VOICE_GATE_THRESHOLD,
                        )
                        if is_match:
                            gate_state = self.self_voice_gate_state.get((int(meeting_id), mic_username))
                            if gate_state is not None:
                                gate_state["allow_output"] = True
                                gate_state["confidence"] = float(confidence)
                                gate_state["distance"] = float(distance)
                            print(f"[VOICEPRINT-ASR] meeting={meeting_id} mic={mic_username} sentence self-match distance={distance:.3f}")
                            return {
                                "username": mic_username,
                                "speaker_id": None,
                                "source": "self_voice_sentence",
                                "confidence": float(confidence),
                                "distance": float(distance),
                                "window_ms": [int(start_ms), int(end_ms)],
                            }
                        gate_state = self.self_voice_gate_state.get((int(meeting_id), mic_username))
                        if gate_state is not None:
                            gate_state["allow_output"] = False
                            gate_state["confidence"] = float(confidence)
                            gate_state["distance"] = float(distance)
                        print(f"[VOICEPRINT-ASR] meeting={meeting_id} mic={mic_username} sentence rejected distance={distance:.3f}")
                        return {
                            "username": None,
                            "speaker_id": None,
                            "source": "self_voice_rejected",
                            "confidence": float(confidence),
                            "distance": float(distance),
                            "window_ms": [int(start_ms), int(end_ms)],
                        }
                    matched_username, confidence, distance = voiceprint_manager.identify_speaker(wav_path)
                finally:
                    try:
                        os.remove(wav_path)
                    except Exception:
                        pass

                if matched_username:
                    print(f"[VOICEPRINT-ASR] meeting={meeting_id} mic={mic_username} no_speaker_id -> {matched_username} distance={distance:.3f}")
                    return {
                        "username": matched_username,
                        "speaker_id": None,
                        "source": "voiceprint_no_speaker_id",
                        "confidence": float(confidence),
                        "distance": float(distance),
                        "window_ms": [int(start_ms), int(end_ms)],
                    }

                print(f"[VOICEPRINT-ASR] meeting={meeting_id} mic={mic_username} no_speaker_id 未匹配，不归属到任何用户")

            if ASR_REQUIRE_VOICEPRINT_IDENTITY:
                return {
                    "username": None,
                    "speaker_id": None,
                    "source": "unverified_no_speaker_id",
                    "confidence": None,
                    "distance": None,
                }
            return {
                "username": mic_username,
                "speaker_id": None,
                "source": "mic_owner",
                "confidence": None,
                "distance": None,
            }

        speaker_id = str(speaker_id)
        if not ASR_SELF_VOICE_GATE_ENABLED and not ASR_REQUIRE_VOICEPRINT_IDENTITY:
            return {
                "username": mic_username,
                "speaker_id": speaker_id,
                "source": "voiceprint_disabled",
                "confidence": None,
                "distance": None,
            }

        key = (int(meeting_id), mic_username)
        cache = self.speaker_identity_cache.setdefault(key, {})
        cached_username = cache.get(speaker_id)
        if speaker_id in cache:
            meta = dict(self.speaker_identity_meta.get((key, speaker_id), {}))
            now_ts = time.time()
            verified_at = float(meta.get("verified_at") or 0)
            hits = int(meta.get("hits") or 0) + 1
            cache_is_fresh = (
                (now_ts - verified_at) <= ASR_SPEAKER_CACHE_TTL_SECONDS
                and hits <= ASR_SPEAKER_CACHE_MAX_HITS
            )
            if cache_is_fresh:
                meta["hits"] = hits
                self.speaker_identity_meta[(key, speaker_id)] = meta
                meta.setdefault("username", cached_username)
                meta.setdefault("speaker_id", speaker_id)
                meta["source"] = "voiceprint_cache"
                return meta
            print(f"[VOICEPRINT-ASR] meeting={meeting_id} mic={mic_username} {speaker_id} 缓存到期，重新声纹复核")

        start_ms, end_ms = self._payload_time_window_ms(key, payload, text)
        pcm_data = self._extract_pcm_segment(key, start_ms, end_ms)
        wav_path = self._write_pcm_segment_wav(pcm_data, meeting_id, speaker_id)
        if not wav_path:
            return {
                "username": None if ASR_REQUIRE_VOICEPRINT_IDENTITY else mic_username,
                "speaker_id": speaker_id,
                "source": "fallback_short_audio",
                "confidence": None,
                "distance": None,
            }

        try:
            matched_username, confidence, distance = voiceprint_manager.identify_speaker(wav_path)
        finally:
            try:
                os.remove(wav_path)
            except Exception:
                pass

        if matched_username:
            if cached_username and cached_username != matched_username:
                print(f"[VOICEPRINT-ASR] meeting={meeting_id} mic={mic_username} {speaker_id} 归属修正: {cached_username} -> {matched_username}")
            cache[speaker_id] = matched_username
            meta = {
                "username": matched_username,
                "speaker_id": speaker_id,
                "source": "voiceprint",
                "confidence": float(confidence),
                "distance": float(distance),
                "window_ms": [int(start_ms), int(end_ms)],
                "verified_at": time.time(),
                "hits": 0,
            }
            self.speaker_identity_meta[(key, speaker_id)] = meta
            print(f"[VOICEPRINT-ASR] meeting={meeting_id} mic={mic_username} {speaker_id} -> {matched_username} distance={distance:.3f}")
            return meta

        if ASR_REQUIRE_VOICEPRINT_IDENTITY:
            print(f"[VOICEPRINT-ASR] meeting={meeting_id} mic={mic_username} {speaker_id} 未匹配，不归属到任何用户")
        else:
            print(f"[VOICEPRINT-ASR] meeting={meeting_id} mic={mic_username} {speaker_id} 未匹配，暂用麦克风用户")
        return {
            "username": None if ASR_REQUIRE_VOICEPRINT_IDENTITY else mic_username,
            "speaker_id": speaker_id,
            "source": "fallback_unmatched",
            "confidence": float(confidence),
            "distance": float(distance),
            "window_ms": [int(start_ms), int(end_ms)],
        }

    async def _dispatch_realtime_analysis(self, prepared: Dict[str, Any]):
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def worker():
            combined = None
            try:
                for event in _stream_realtime_speech_analysis_events(prepared):
                    if not isinstance(event, dict):
                        continue
                    if "__combined" in event:
                        combined = event.get("__combined")
                        continue
                    asyncio.run_coroutine_threadsafe(queue.put(event), loop)

                for event in _run_realtime_speech_analysis(prepared, precomputed_combined=combined) or []:
                    asyncio.run_coroutine_threadsafe(queue.put(event), loop)
            except Exception as e:
                print(f"[ASR ERROR] 实时评分广播失败: {e}")
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(None), loop)

        threading.Thread(target=worker, daemon=True).start()

        while True:
            event = await queue.get()
            if event is None:
                break
            await manager.broadcast_to_meeting(int(prepared["meeting_id"]), event)

    async def _flush_merged_sentence(self, meeting_id: int, username: str):
        """将缓冲区中的合并句子发送出去"""
        key = (int(meeting_id), username)
        buffer = self.sentence_merge_buffer.get(key)
        if not buffer or not buffer.get("text"):
            return

        merged_text = buffer["text"]
        identity = buffer.get("identity")
        speaker_id = buffer.get("speaker_id")
        asr_sentence_id = buffer.get("asr_sentence_id")
        asr_index = buffer.get("asr_index")
        audio_volume = float(buffer.get("audio_volume") or 0.0)

        print(f"[SENTENCE-MERGE] 发送合并句子: {username}@meeting{meeting_id}, 长度={len(merged_text)}, 文本={merged_text[:50]}")

        # 发送 asr_final 作为中间结果
        display_username = identity.get("username") if identity else username
        asr_payload = {
            "type": "asr_final",
            "username": display_username or ASR_UNKNOWN_SPEAKER_LABEL,
            "text": merged_text
        }
        if asr_sentence_id:
            asr_payload["asr_sentence_id"] = asr_sentence_id
        if asr_index is not None:
            asr_payload["asr_index"] = asr_index
        if speaker_id:
            asr_payload["speaker_id"] = speaker_id
        if identity and identity.get("source"):
            asr_payload["identity_source"] = identity.get("source")
        if identity and identity.get("confidence") is not None:
            asr_payload["voiceprint_confidence"] = identity.get("confidence")
        if not display_username:
            asr_payload["identity_unverified"] = True

        # 先把最终转写推给前端，保证聊天栏不被入库、去重或 AI 评分阻塞。
        # 如果后续被判定为重复或小音量串音，会发送 asr_rejected 清掉临时卡片。
        await self._broadcast_to_meeting(meeting_id, asr_payload)
        await manager.broadcast_to_meeting(meeting_id, asr_payload)

        # 如果身份已确认，入库并触发 AI 分析
        if display_username:
            prepared = await asyncio.to_thread(
                _create_realtime_transcript_entry,
                display_username,
                meeting_id,
                merged_text,
                audio_volume,
                asr_sentence_id,
                asr_index,
            )
            if prepared:
                if speaker_id:
                    prepared["fast_payload"]["speaker_id"] = speaker_id
                if identity and identity.get("source"):
                    prepared["fast_payload"]["identity_source"] = identity.get("source")
                if identity and identity.get("confidence") is not None:
                    prepared["fast_payload"]["voiceprint_confidence"] = identity.get("confidence")
                if identity and identity.get("distance") is not None:
                    prepared["fast_payload"]["voiceprint_distance"] = identity.get("distance")

                await manager.broadcast_to_meeting(meeting_id, prepared["fast_payload"])
                asyncio.create_task(self._dispatch_realtime_analysis(prepared))
            else:
                rejected_payload = {
                    "type": "asr_rejected",
                    "username": display_username,
                    "reason": "duplicate_or_lower_volume",
                }
                if asr_sentence_id:
                    rejected_payload["asr_sentence_id"] = asr_sentence_id
                if asr_index is not None:
                    rejected_payload["asr_index"] = asr_index
                await self._broadcast_to_meeting(meeting_id, rejected_payload)
                await manager.broadcast_to_meeting(meeting_id, rejected_payload)

        # 清空缓冲区
        self.sentence_merge_buffer.pop(key, None)
        gate_state = self.self_voice_gate_state.get(key)
        if gate_state is not None:
            gate_state["allow_output"] = False
            gate_state["sentence_locked"] = False
            gate_state["active_sentence_id"] = None
            gate_state["verified_sentence_id"] = None
            gate_state["pending_gate_pass"] = False
            gate_state["checking"] = False

    async def _handle_final_result(self, meeting_id: int, username: str, text: str, payload: Optional[Dict[str, Any]] = None):
        identity = await asyncio.to_thread(
            self._resolve_speaker_identity_sync,
            meeting_id,
            username,
            text,
            payload or {},
        )
        resolved_username = identity.get("username")
        display_username = resolved_username or ASR_UNKNOWN_SPEAKER_LABEL
        speaker_id = identity.get("speaker_id")

        # 临时禁用声纹门控检查，允许所有语音转文字输出
        # if ASR_SELF_VOICE_GATE_ENABLED and resolved_username != username:
        #     gate_state = self.self_voice_gate_state.get((int(meeting_id), username))
        #     if gate_state is not None:
        #         gate_state["allow_output"] = False
        #         gate_state["sentence_locked"] = False
        #         gate_state["active_sentence_id"] = None
        #         gate_state["verified_sentence_id"] = None
        #         gate_state["pending_gate_pass"] = False
        #         gate_state["checking"] = False
        #     sentence_index = (payload or {}).get("index")
        #     rejected_payload = {
        #         "type": "asr_rejected",
        #         "username": username,
        #         "reason": identity.get("source") or "voiceprint_rejected",
        #         "confidence": identity.get("confidence"),
        #         "distance": identity.get("distance"),
        #     }
        #     if sentence_index is not None:
        #         rejected_payload["asr_sentence_id"] = f"{int(meeting_id)}:{username}:{sentence_index}"
        #         rejected_payload["asr_index"] = sentence_index
        #     await self._broadcast_to_meeting(meeting_id, rejected_payload)
        #     print(
        #         f"[ASR] 跳过非本人最终转写: mic={username}, "
        #         f"resolved={resolved_username}, text={str(text or '')[:30]}"
        #     )
        #     return

        clean_text = str(text or "").strip()
        if not clean_text:
            return
        sentence_index = (payload or {}).get("index")
        sentence_id = f"{int(meeting_id)}:{username}:{sentence_index}" if sentence_index is not None else None
        try:
            start_ms, end_ms = self._payload_time_window_ms((int(meeting_id), username), payload or {}, clean_text)
            sentence_pcm = self._extract_pcm_segment((int(meeting_id), username), start_ms, end_ms)
            sentence_volume = self._pcm_rms(sentence_pcm)
        except Exception:
            sentence_volume = 0.0

        # ===== 句子合并逻辑 =====
        # 将3秒内的多个句子合并成一条消息
        key = (int(meeting_id), username)
        buffer = self.sentence_merge_buffer.get(key)

        if buffer is None:
            # 首次收到句子，创建缓冲区
            self.sentence_merge_buffer[key] = {
                "text": clean_text,
                "last_time": time.time(),
                "identity": identity,
                "speaker_id": speaker_id,
                "asr_sentence_id": sentence_id,
                "asr_index": sentence_index,
                "audio_volume": sentence_volume,
                "timer": None
            }
            buffer = self.sentence_merge_buffer[key]
            print(f"[SENTENCE-MERGE] 开始新句子: {username}@meeting{meeting_id}, 文本={clean_text[:30]}")
        else:
            # 追加到现有句子
            buffer["text"] += clean_text
            buffer["last_time"] = time.time()
            if sentence_id and not buffer.get("asr_sentence_id"):
                buffer["asr_sentence_id"] = sentence_id
            if sentence_index is not None and buffer.get("asr_index") is None:
                buffer["asr_index"] = sentence_index
            buffer["audio_volume"] = max(float(buffer.get("audio_volume") or 0.0), float(sentence_volume or 0.0))
            # 取消之前的定时器
            if buffer.get("timer"):
                buffer["timer"].cancel()
            print(f"[SENTENCE-MERGE] 追加句子: {username}@meeting{meeting_id}, 当前长度={len(buffer['text'])}")

        # 设置3秒后自动发送的定时器
        async def delayed_flush():
            await asyncio.sleep(ASR_SENTENCE_END_SILENCE_SECONDS)
            await self._flush_merged_sentence(meeting_id, username)

        buffer["timer"] = asyncio.create_task(delayed_flush())

        # 句子已缓冲，等待定时器触发发送，不立即发送
        return

    async def start_session(self, username, meeting_id, client_ws):
        """为用户创建阿里云 NLS 实时转写会话"""
        key = (meeting_id, username)

        # 记录连接
        if meeting_id not in self.meeting_connections:
            self.meeting_connections[meeting_id] = {}
        self.meeting_connections[meeting_id][username] = client_ws

        # 获取当前事件循环用于线程安全回调
        loop = asyncio.get_running_loop()

        def on_partial(text, payload=None):
            """阿里云回调线程 → 异步广播中间结果"""
            payload = payload or {}
            sentence_index = payload.get("index")
            sentence_id = f"{int(meeting_id)}:{username}:{sentence_index}" if sentence_index is not None else None
            if ASR_SELF_VOICE_GATE_ENABLED:
                gate_state = self.self_voice_gate_state.setdefault((int(meeting_id), username), {
                    "last_check_ms": 0,
                    "last_voice_ms": 0,
                    "allow_output": False,
                    "checking": False,
                    "check_token": 0,
                })
                if sentence_id and gate_state.get("active_sentence_id") != sentence_id:
                    last_pass_at = float(gate_state.get("last_pass_at") or 0)
                    pass_recent = bool(last_pass_at and (time.time() - last_pass_at) <= 8.0)
                    keep_pass_for_sentence = bool(
                        gate_state.get("allow_output")
                        and pass_recent
                    )
                    gate_state["active_sentence_id"] = sentence_id
                    gate_state["checking"] = False
                    gate_state["last_check_ms"] = 0
                    gate_state["fail_count"] = 0
                    gate_state["check_token"] = int(gate_state.get("check_token") or 0) + 1
                    if keep_pass_for_sentence:
                        gate_state["allow_output"] = True
                        gate_state["verified_sentence_id"] = sentence_id
                        gate_state["pending_gate_pass"] = False
                        gate_state["sentence_locked"] = True
                    else:
                        gate_state["allow_output"] = False
                        gate_state["verified_sentence_id"] = None
                        gate_state["pending_gate_pass"] = False
                        gate_state["sentence_locked"] = False
                # 临时禁用声纹门控检查，允许所有语音转文字输出
                # if not gate_state.get("allow_output"):
                #     return
            speaker_id = payload.get("speaker_id") or payload.get("speakerId") or payload.get("speaker") or payload.get("spk")
            display_username = username
            if speaker_id and not REALTIME_ASR_VOICEPRINT_DISABLED and (ASR_SELF_VOICE_GATE_ENABLED or ASR_REQUIRE_VOICEPRINT_IDENTITY):
                cached = self.speaker_identity_cache.get((int(meeting_id), username), {}).get(str(speaker_id))
                if cached:
                    display_username = cached
                else:
                    # 首次出现的 speaker_id 先等 SentenceEnd 做声纹确认，
                    # 避免把中间结果短暂显示到麦克风持有人名下。
                    return
            msg = {
                "type": "asr_partial",
                "username": display_username,
                "text": text
            }
            if sentence_index is not None:
                msg["asr_sentence_id"] = f"{int(meeting_id)}:{username}:{sentence_index}"
                msg["asr_index"] = sentence_index
            if speaker_id:
                msg["speaker_id"] = str(speaker_id)
            asyncio.run_coroutine_threadsafe(
                self._broadcast_to_meeting(meeting_id, msg),
                loop
            )

        def on_final(text, payload=None):
            """阿里云回调线程 → 异步广播最终结果"""
            asyncio.run_coroutine_threadsafe(
                self._handle_final_result(meeting_id, username, text, payload or {}),
                loop
            )

        def on_error(msg):
            print(f"[ASR ERROR] {username}@meeting{meeting_id}: {msg}")

        from app.services.ai_core import RealtimeTranscriber

        # 实时语音识别官方接口不支持说话人分离。
        # 这里仅使用阿里云做实时转写，真实用户归属由本地声纹按句子音频片段确认。
        use_aliyun_diarization = False

        if use_aliyun_diarization:
            # 阿里云原生方案
            transcriber = RealtimeTranscriber(
                on_partial=on_partial,
                on_final=on_final,
                on_error=on_error,
                enable_speaker_diarization=True,
                username=username
            )
        else:
            # 标准方案（原来的）
            transcriber = RealtimeTranscriber(
                on_partial=on_partial,
                on_final=on_final,
                on_error=on_error
            )

        # transcriber.start() 是同步方法，会阻塞事件循环，需要在线程池中执行
        loop = asyncio.get_running_loop()
        success = await loop.run_in_executor(None, transcriber.start)

        if success:
            old_transcriber = self.sessions.get(key)
            if old_transcriber and old_transcriber is not transcriber:
                try:
                    old_transcriber.stop()
                except Exception:
                    pass
            self.sessions[key] = transcriber
            self.session_websockets[key] = client_ws
            print(f"[ASR] 实时会话已启动: {username}@meeting{meeting_id}")
        else:
            print(f"[ASR ERROR] 会话启动失败: {username}@meeting{meeting_id}")

        return success

    def feed_audio(self, username, meeting_id, pcm_data: bytes):
        """将 PCM 音频数据转发给用户的阿里云 NLS 会话"""
        key = (meeting_id, username)
        transcriber = self.sessions.get(key)
        if transcriber and transcriber.is_started:
            transcriber.feed_audio(pcm_data)

    async def stop_session(self, username, meeting_id, client_ws=None):
        """停止并清理用户的 ASR 会话"""
        key = (meeting_id, username)
        current_ws = self.session_websockets.get(key) or self.meeting_connections.get(meeting_id, {}).get(username)
        if client_ws is not None and current_ws is not None and current_ws is not client_ws:
            print(f"[ASR] 忽略旧WebSocket清理: {username}@meeting{meeting_id}")
            return
        transcriber = self.sessions.pop(key, None)
        self.session_websockets.pop(key, None)
        if transcriber:
            transcriber.stop()
            print(f"[ASR] 会话已停止: {username}@meeting{meeting_id}")

        if meeting_id in self.meeting_connections:
            if client_ws is None or self.meeting_connections[meeting_id].get(username) is client_ws:
                self.meeting_connections[meeting_id].pop(username, None)
        key = (int(meeting_id), username)
        self.pcm_buffers.pop(key, None)
        self.pcm_total_ms.pop(key, None)
        self.self_voice_gate_state.pop(key, None)
        self.speaker_identity_cache.pop(key, None)
        for meta_key in list(self.speaker_identity_meta.keys()):
            if meta_key[0] == key:
                self.speaker_identity_meta.pop(meta_key, None)

    async def _broadcast_to_meeting(self, meeting_id, msg):
        """将 ASR 结果广播给课堂所有成员"""
        connections = self.meeting_connections.get(meeting_id, {})
        for uname, ws in list(connections.items()):
            try:
                await ws.send_json(msg)
            except Exception:
                pass


asr_manager = ASRSessionManager()


@app.websocket("/ws-signal/{username}/{meeting_id}")
async def websocket_signal_endpoint(websocket: WebSocket, username: str, meeting_id: int):
    """
    WebRTC 信令通道：转发 webrtc_offer / webrtc_answer / webrtc_ice / webrtc_hangup。
    from 字段强制为连接身份，防止伪造。
    """
    await signal_manager.register(websocket, meeting_id, username)
    print(f"[SIGNAL] WebSocket: {username} -> meeting{meeting_id}")
    try:
        while True:
            data = await websocket.receive_json()
            t = data.get("type")
            if t not in ("webrtc_offer", "webrtc_answer", "webrtc_ice", "webrtc_hangup"):
                continue
            target = data.get("to")
            if not target or target == username:
                continue
            data["from"] = username
            ok = await signal_manager.forward_to(meeting_id, target, data)
            if not ok:
                print(f"[SIGNAL] 转发失败: {username} -> {target}")
    except Exception as e:
        print(f"[SIGNAL] 断开: {username} - {type(e).__name__}: {e}")
    finally:
        signal_manager.unregister(meeting_id, username)


@app.websocket("/ws-asr/{username}/{meeting_id}")
async def websocket_asr_endpoint(websocket: WebSocket, username: str, meeting_id: int):
    """
    实时语音识别 WebSocket 端点。
    接收前端发来的 PCM 音频数据（二进制），转发给阿里云 NLS，
    将中间/最终识别结果广播给课堂所有成员。
    延迟启动：收到第一个音频包后才创建阿里云 NLS 会话。
    """
    await websocket.accept()
    print(f"[ASR] WebSocket连接: {username} -> meeting{meeting_id}")

    # 记录连接但不立即启动阿里云会话
    if meeting_id not in asr_manager.meeting_connections:
        asr_manager.meeting_connections[meeting_id] = {}
    asr_manager.meeting_connections[meeting_id][username] = websocket

    session_started = False
    try:
        while True:
            data = await websocket.receive_bytes()
            if len(data) > 0:
                key = (int(meeting_id), username)
                asr_manager._append_pcm_buffer(meeting_id, username, data)

                # 阿里云会话收到音频后立即启动；当前实时转文字不再使用声纹门控。
                if not session_started:
                    print(f"[ASR] 启动阿里云实时会话，声纹门控已关闭: {username}")
                    success = await asr_manager.start_session(username, meeting_id, websocket)
                    if not success:
                        print(f"[ASR] 阿里云会话启动失败，继续接收但不转发")
                        try:
                            await websocket.send_json({
                                "type": "asr_error",
                                "message": "阿里云实时转写会话启动失败，请检查服务器网络或 ASR 配置"
                            })
                        except Exception:
                            pass
                        session_started = True
                        continue
                    session_started = True
                    try:
                        status_message = "Aliyun realtime ASR started"
                        await websocket.send_json({
                            "type": "asr_status",
                            "message": status_message
                        })
                    except Exception:
                        pass

                # Keep Aliyun ASR hot from the first PCM frame. The self-voice gate
                # only controls whether callbacks may broadcast/persist text.
                asr_manager.feed_audio(username, meeting_id, data)

                if ASR_SELF_VOICE_GATE_ENABLED and not REALTIME_ASR_VOICEPRINT_DISABLED:
                    state = asr_manager.self_voice_gate_state.setdefault(key, {
                        "last_check_ms": 0,
                        "last_voice_ms": 0,
                        "allow_output": False,
                        "checking": False,
                        "check_token": 0,
                    })
                    total_ms = asr_manager.pcm_total_ms.get(key, 0)
                    rms = asr_manager._pcm_rms(data)
                    if rms >= ASR_SELF_VOICE_GATE_RMS_THRESHOLD:
                        state["last_voice_ms"] = total_ms

                    gate_open = bool(state.get("allow_output"))
                    if (
                        gate_open
                        and not state.get("sentence_locked")
                        and not state.get("active_sentence_id")
                        and state.get("last_voice_ms")
                        and (total_ms - state["last_voice_ms"]) >= ASR_SELF_VOICE_GATE_SILENCE_MS
                    ):
                        print(f"[ASR] {username}@meeting{meeting_id} silence, close legacy self voice gate")
                        state["allow_output"] = False
                        state["sentence_locked"] = False
                        continue

                    if not bool(state.get("allow_output")):
                        available_ms = min(total_ms, ASR_SELF_VOICE_GATE_WINDOW_MS)
                        if available_ms < ASR_SELF_VOICE_GATE_MIN_MS:
                            continue
                        if (total_ms - int(state.get("last_check_ms") or 0)) < ASR_SELF_VOICE_GATE_CHECK_INTERVAL_MS:
                            continue
                        if state.get("checking"):
                            continue
                        state["last_check_ms"] = total_ms
                        gate_pcm = asr_manager._get_recent_pcm(key, ASR_SELF_VOICE_GATE_WINDOW_MS)
                        state["checking"] = True
                        state["check_token"] = int(state.get("check_token") or 0) + 1
                        asyncio.create_task(
                            asr_manager._run_self_voice_gate_check(
                                int(meeting_id),
                                username,
                                key,
                                gate_pcm,
                                state["check_token"],
                            )
                        )

    except Exception as e:
        print(f"[ASR] WebSocket断开: {username} - {type(e).__name__}")
    finally:
        await asr_manager.stop_session(username, meeting_id, websocket)


@app.websocket("/ws/{username}/{meeting_id}")
async def websocket_endpoint(websocket: WebSocket, username: str, meeting_id: int):
    await manager.connect(websocket, meeting_id, username)
    print(f"[OK] WebSocket连接成功: {username} -> 课堂{meeting_id}")

    # 广播成员加入
    online_members = manager.get_online_members(meeting_id)
    await manager.broadcast_to_meeting(meeting_id, {
        "type": "member_update",
        "action": "join",
        "username": username,
        "online_members": online_members
    })

    try:
        while True:
            # 接收消息（支持 bytes 和 text 类型）
            message = await websocket.receive()

            # 处理心跳消息
            if "text" in message:
                text_data = message["text"]
                if text_data == "ping":
                    await websocket.send_text("pong")
                    continue

            # 处理音视频数据
            if "bytes" in message:
                data = message["bytes"]
                print(f"[DATA] 收到数据: {len(data)} 字节")

                if len(data) > 0:
                    # 处理音视频流
                    print(f"[PROCESS] 处理中...")
                    import asyncio
                    import queue

                    result_queue = queue.Queue()

                    def run_generator():
                        """在线程池中运行同步generator，逐个放入队列"""
                        try:
                            for result in process_user_stream_generator(username, data, int(meeting_id)):
                                result_queue.put(result)
                        except Exception as e:
                            print(f"[ERROR] generator异常: {e}")
                        finally:
                            result_queue.put(None)  # 结束标记

                    # 在线程池中启动generator
                    loop = asyncio.get_event_loop()
                    future = loop.run_in_executor(None, run_generator)

                    # 异步轮询队列，每个结果立即广播
                    result_count = 0
                    while True:
                        try:
                            result = result_queue.get_nowait()
                        except queue.Empty:
                            await asyncio.sleep(0.05)
                            continue
                        if result is None:
                            break
                        result_count += 1
                        print(f"[SEND] 发送第{result_count}条结果: {result.get('type', 'unknown')}")
                        await manager.broadcast_to_meeting(meeting_id, result)

                    await future  # 确保线程完成
                    print(f"[OK] 处理完成{result_count}条结果")
    except Exception as e:
        print(f"[WARN] WebSocket断开连接: {username} - {type(e).__name__}")
        manager.disconnect(websocket, meeting_id, username)
        # 广播成员离开
        online_members = manager.get_online_members(meeting_id)
        await manager.broadcast_to_meeting(meeting_id, {
            "type": "member_update",
            "action": "leave",
            "username": username,
            "online_members": online_members
        })


@app.post("/api/ai-tutor")
async def ai_tutor(question: str = Form(...)):
    """
    AI导师接口
    学生提问，返回AI解答
    """
    try:
        if not question or not question.strip():
            return {"status": "error", "answer": "问题不能为空"}

        question = question.strip()
        print(f"收到 AI导师提问: {question}")

        # 复用 llm_service 内部的 client / 缓存
        answer = llm.ai_tutor(question)

        if not answer:
            answer = "抱歉，我暂时无法回答这个问题。"

        print(f"[OK] AI导师回答: {answer[:100]}...")
        return {"status": "success", "answer": answer}

    except Exception as e:
        print(f"[ERROR] AI导师失败: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "answer": f"抱歉，AI导师暂时无法回答: {str(e)}"}

@app.post("/api/browser-asr-final")
async def browser_asr_final(
    meeting_id: int = Form(...),
    username: str = Form(...),
    text: str = Form(...),
):
    """浏览器原生语音识别兜底：将最终句子回写到课堂流和报告链路"""
    clean_text = str(text or "").strip()
    if not clean_text:
        return {"status": "ignored", "message": "empty text"}

    prepared = await asyncio.to_thread(
        _create_realtime_transcript_entry,
        username,
        int(meeting_id),
        clean_text,
    )
    if not prepared:
        return {"status": "ignored", "message": "duplicate or invalid"}

    await manager.broadcast_to_meeting(int(meeting_id), prepared["fast_payload"])
    asyncio.create_task(asr_manager._dispatch_realtime_analysis(prepared))
    return {
        "status": "success",
        "transcript_id": prepared["transcript_id"],
        "text": clean_text,
    }


@app.post("/api/check-silence")
async def check_silence(
    meeting_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """检查课堂是否沉默超过2分钟，如果是则生成话题建议"""
    try:
        if not manager.is_group_silent(meeting_id, silence_seconds=120):
            return {"status": "ok", "silent": False}

        if manager.silence_notified.get(meeting_id):
            return {"status": "ok", "silent": True, "already_notified": True}

        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"status": "error", "message": "课堂不存在"}

        # 获取最近讨论上下文
        recents = db.query(Transcript).filter(
            Transcript.meeting_id == meeting_id
        ).order_by(Transcript.id.desc()).limit(5).all()
        ctx = "\n".join([f"{t.user.username}: {t.content}" for t in reversed(recents)])

        suggestion = llm.generate_topic_suggestion(
            meeting.topic, ctx, meeting.knowledge_points, target_type="group"
        )

        # 广播给所有在线成员
        await manager.broadcast_to_meeting(meeting_id, {
            "type": "topic_suggestion",
            "target": "all",
            "suggestion": suggestion,
            "reason": "group_silence"
        })
        manager.silence_notified[meeting_id] = True

        return {"status": "success", "silent": True, "suggestion": suggestion}
    except Exception as e:
        print(f"[ERROR] check-silence: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/check-quiet-members")
async def check_quiet_members(
    meeting_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """检查发言少的成员并推送个性化话题建议"""
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"status": "error", "message": "课堂不存在"}

        quiet_members = manager.get_quiet_members(meeting_id, threshold=2)
        if not quiet_members:
            return {"status": "ok", "quiet_members": []}

        # 获取讨论上下文
        recents = db.query(Transcript).filter(
            Transcript.meeting_id == meeting_id
        ).order_by(Transcript.id.desc()).limit(5).all()
        ctx = "\n".join([f"{t.user.username}: {t.content}" for t in reversed(recents)])

        suggestion = llm.generate_topic_suggestion(
            meeting.topic, ctx, meeting.knowledge_points, target_type="quiet"
        )

        # 只推送给沉默的成员
        for member in quiet_members:
            await manager.send_to_user(meeting_id, member, {
                "type": "topic_suggestion",
                "target": "personal",
                "suggestion": suggestion,
                "reason": "low_participation"
            })

        return {"status": "success", "quiet_members": quiet_members, "suggestion": suggestion}
    except Exception as e:
        print(f"[ERROR] check-quiet-members: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/ai-tutor-stream")
async def ai_tutor_stream(question: str = Form(...), history: str = Form(default="[]")):
    """
    AI导师流式接口 - SSE
    """
    import json as _json

    def generate():
        try:
            q = question.strip()
            if not q:
                yield f"data: 问题不能为空\n\n"
                yield "data: [DONE]\n\n"
                return

            # 解析历史对话
            try:
                hist = _json.loads(history) if history else []
            except Exception:
                hist = []

            print(f"[STREAM] AI导师提问: {q}")
            for token in llm.ai_tutor_stream(q, hist):
                # SSE 格式：每行 data: xxx，用双换行分隔
                yield f"data: {_json.dumps(token, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            print(f"[OK] AI导师流式回答完成")
        except Exception as e:
            print(f"[ERROR] AI导师流式失败: {e}")
            yield f"data: {_json.dumps('抱歉，系统出错，请重试。', ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")







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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
