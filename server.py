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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(BASE_DIR, '1'))
sys.path.append(os.path.join(BASE_DIR, '2'))
LOCAL_AGORA_TOKEN_BUILDER_DIR = os.path.join(BASE_DIR, '_tmp_agora_token_builder')
if os.path.isdir(LOCAL_AGORA_TOKEN_BUILDER_DIR):
    sys.path.append(LOCAL_AGORA_TOKEN_BUILDER_DIR)

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

from database import get_db, User, Meeting, Transcript, EmotionLog, AIInsight, KnowledgeGraph, LearningReport, Exercise, StudentAnswer, SessionLocal, ViewpointVote, MemberConnection
from llm_service import llm
from knowledge_graph_service import kg_service
from config import (
    apply_research_runtime_config,
    ensure_research_directories,
    get_research_runtime_settings_snapshot,
    persist_research_runtime_config,
)
from research_runtime import research_runtime

# 📦 OSS📦
try:
    from oss_utils import get_oss_manager
    USE_OSS = True
    print("OSS module imported")
except Exception as e:
    USE_OSS = False
    print(f"OSS not configured: {e}")

try:
    from ai_core import engine
except ImportError:
    sys.exit(1)

# 导入声纹管理器
from voiceprint_manager import voiceprint_manager

ROOT_DIR = os.getcwd()
for d in ["storage", "storage/video_chunks", "storage/audio_chunks", "storage/snapshots"]:
    os.makedirs(os.path.join(ROOT_DIR, d), exist_ok=True)

app = FastAPI()

NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

# 🔧 CORS🔧
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 🌍
    allow_credentials=True,
    allow_methods=["*"],  # 🌍
    allow_headers=["*"],  # 🌍
)

app.mount("/storage", StaticFiles(directory="storage"), name="storage")

# 🔊 analyzer🔊
analyzer = None

def get_analyzer():
    """🔊 analyzer🔊"""
    global analyzer
    if analyzer is None:
        from video_processor import VideoEmotionAnalyzer
        analyzer = VideoEmotionAnalyzer()
    return analyzer


def resolve_user_by_identifier(db: Session, identifier: str):
    if not identifier:
        return None
    user = db.query(User).filter(User.student_id == identifier).first()
    if user:
        return user
    return db.query(User).filter(User.username == identifier).first()


def normalize_emotion_label(label: str) -> str:
    raw = str(label or "").strip().lower()
    if not raw:
        return "neutral"
    raw = raw.split("|", 1)[0].strip()
    raw = raw.replace(" ", "_").replace("-", "_")

    aliases = {
        "happy": "happy",
        "happiness": "happy",
        "joy": "happy",
        "joyful": "happy",
        "smile": "happy",
        "smiling": "happy",
        "pleased": "happy",
        "delight": "happy",
        "positive": "happy",
        "\u5f00\u5fc3": "happy",
        "\u9ad8\u5174": "happy",
        "\u5feb\u4e50": "happy",
        "\u5fae\u7b11": "happy",
        "excited": "excited",
        "excite": "excited",
        "energetic": "excited",
        "active": "excited",
        "\u5174\u594b": "excited",
        "surprise": "surprised",
        "surprised": "surprised",
        "surprise/excited": "surprised",
        "\u60ca\u559c": "surprised",
        "\u60ca\u8bb6": "surprised",
        "calm": "calm",
        "relaxed": "calm",
        "relax": "calm",
        "peaceful": "calm",
        "\u5e73\u9759": "calm",
        "neutral": "neutral",
        "normal": "neutral",
        "thinking": "thinking",
        "thoughtful": "thinking",
        "focused": "thinking",
        "focus": "thinking",
        "\u601d\u8003": "thinking",
        "confused": "confused",
        "confusion": "confused",
        "uncertain": "confused",
        "fear": "confused",
        "fearful": "confused",
        "anxious": "confused",
        "worried": "confused",
        "nervous": "confused",
        "disgust": "confused",
        "contempt": "confused",
        "anxious/frown": "confused",
        "\u56f0\u60d1": "confused",
        "\u62c5\u5fc3": "confused",
        "sad": "sad",
        "sadness": "sad",
        "down": "sad",
        "unhappy": "sad",
        "\u96be\u8fc7": "sad",
        "angry": "angry",
        "anger": "angry",
        "mad": "angry",
        "\u751f\u6c14": "angry",
    }

    if raw in aliases:
        return aliases[raw]

    for part in re.split(r"[/,;]+", raw):
        part = part.strip()
        if part in aliases:
            return aliases[part]

    return raw or "neutral"


def emotion_value_for_label(label: str) -> int:
    values = {
        "excited": 92,
        "happy": 85,
        "surprised": 75,
        "calm": 60,
        "neutral": 50,
        "thinking": 45,
        "confused": 35,
        "sad": 25,
        "angry": 15,
    }
    return values.get(normalize_emotion_label(label), 50)


def map_silent_emotion(face_emotion: str) -> str:
    e = normalize_emotion_label(face_emotion)
    if e in ("happy", "excited", "surprised"):
        return "happy"
    if e in ("sad", "angry"):
        return e
    if e in ("confused", "thinking"):
        return "sad"
    if e in ("calm", "neutral", "relaxed"):
        return "calm"
    return "calm"


def map_speaking_emotion(face_emotion: str, tone: str) -> str:
    fe = normalize_emotion_label(face_emotion)
    t = (tone or "").strip().lower()

    if fe in ("happy", "excited", "surprised"):
        return "excited" if t == "loud" else ("happy" if fe == "happy" else fe)
    if fe in ("angry", "sad", "confused"):
        return fe

    if t == "loud":
        return "excited"

    if t == "quiet":
        if fe in ("thinking",):
            return "thinking"
        if fe in ("neutral", "calm"):
            return "calm"
        return fe or "calm"

    if fe and fe != "neutral":
        return fe
    return "neutral"


# 🎙 ?80
def is_speaking(audio_path, threshold=20):  #  ?🎙 ?0🎙 ?0🎙 ?
    try:
        with wave.open(audio_path, 'rb') as wf:
            frames = wf.readframes(wf.getnframes())
            data = np.frombuffer(frames, dtype=np.int16)
            if len(data) == 0: return False
            rms = np.sqrt(np.mean(data.astype(np.float64) ** 2))
            is_speech = rms > threshold
            result_text = "🎤" if is_speech else "😶"
            print(f"[AUDIO] 🎙 ? RMS={int(rms)}, 🎙 ?{threshold}, 🎙 ?{result_text}")
            return is_speech
    except Exception as e:
        print(f"[ERROR] VAD🎙 ? {e}")
        return False


def analyze_audio_tone(audio_path):
    try:
        with wave.open(audio_path, 'rb') as wf:
            data = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
            if len(data) == 0: return False, "silent"
            rms = np.sqrt(np.mean(data.astype(np.float64) ** 2))
            if rms > 2000: return True, "loud"
            if rms > 500: return True, "normal"
            if rms > 20: return True, "quiet"
            return False, "silent"
    except:
        return False, "silent"


def _emotion_selection_key(emotion: str, confidence: float):
    emotion = normalize_emotion_label(emotion)
    priority = {
        "excited": 8,
        "happy": 7,
        "surprised": 6,
        "angry": 5,
        "sad": 4,
        "confused": 3,
        "thinking": 2,
        "calm": 1,
        "neutral": 0,
    }.get(emotion, 0)
    try:
        conf = float(confidence or 0.0)
    except Exception:
        conf = 0.0
    expressive = 1 if priority >= 2 else 0
    return expressive, priority, conf


def _body_action_key(action: str, score: float = 0.0):
    priority = {
        "high_activity": 3,
        "normal_gesture": 2,
        "calm": 1,
        "static": 0,
    }.get(str(action or "").strip().lower(), 0)
    try:
        movement = float(score or 0.0)
    except Exception:
        movement = 0.0
    return priority, movement


def _detect_visual_state_from_video(video_path: str, max_samples: int = 3):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return False, None, "neutral", 0.0, "static"

    sampled = 0
    first_frame = None
    best_frame = None
    best_emotion = "neutral"
    best_confidence = 0.0
    best_key = _emotion_selection_key(best_emotion, best_confidence)
    best_action = "static"
    best_action_key = _body_action_key(best_action, 0.0)

    try:
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        frames = []
        if frame_count > 3:
            sample_indices = sorted(set([
                max(0, min(frame_count - 1, int(frame_count * 0.15))),
                max(0, min(frame_count - 1, int(frame_count * 0.50))),
                max(0, min(frame_count - 1, int(frame_count * 0.85))),
            ]))[:max_samples]
            for idx in sample_indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ret, frame = cap.read()
                if ret and frame is not None:
                    frames.append(frame)
        else:
            for _ in range(max_samples):
                ret, frame = cap.read()
                if ret and frame is not None:
                    frames.append(frame)
                for _ in range(8):
                    if not cap.grab():
                        break

        if not frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            for _ in range(max_samples):
                ret, frame = cap.read()
                if ret and frame is not None:
                    frames.append(frame)
                for _ in range(8):
                    if not cap.grab():
                        break

        analyzer_ref = get_analyzer()
        for frame in frames:
            sampled += 1
            if first_frame is None:
                first_frame = frame

            e_type, e_conf, _ = analyzer_ref.detect_emotion(frame)
            emotion = normalize_emotion_label(e_type)
            emotion_key = _emotion_selection_key(emotion, e_conf)
            if emotion_key > best_key:
                best_key = emotion_key
                best_emotion = emotion
                best_confidence = float(e_conf or 0.0)
                best_frame = frame

            movement_score, movement_desc = analyzer_ref.detect_body_movement(frame)
            action_key = _body_action_key(movement_desc, movement_score)
            if action_key > best_action_key:
                best_action_key = action_key
                best_action = movement_desc or best_action

        if best_frame is None:
            best_frame = first_frame

        # 如果最终结果是 neutral/calm，强制用 MediaPipe 复核
        if best_emotion in ("neutral", "calm") and best_frame is not None:
            try:
                # 直接调用 MediaPipe 复核
                import cv2
                face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
                gray = cv2.cvtColor(best_frame, cv2.COLOR_BGR2GRAY)
                faces = face_cascade.detectMultiScale(gray, 1.1, 4)
                if len(faces) > 0:
                    x, y, w, h = faces[0]
                    face_rgb = cv2.cvtColor(best_frame[y:y+h, x:x+w], cv2.COLOR_BGR2RGB)
                    refined_emotion, refined_conf = analyzer_ref._mediapipe_refine(face_rgb)
                    if refined_emotion:
                        print(f"[EmotionState] MediaPipe 复核覆盖: {best_emotion} -> {refined_emotion} ({refined_conf:.2f})")
                        best_emotion = refined_emotion
                        best_confidence = refined_conf
            except Exception as e:
                print(f"[EmotionState] MediaPipe 复核失败: {e}")

        if sampled:
            print(f"[EmotionState] sampled={sampled}, emotion={best_emotion}, confidence={best_confidence:.2f}, action={best_action}")
        return best_frame is not None, best_frame, best_emotion, best_confidence, best_action
    finally:
        cap.release()


# 🧠 (🧠10🧠)
kg_counter = {}
# 同一课堂内的短时转写去重缓存：避免同一句话被多端同时写成多条“各自发言”
# 结构: { (meeting_id, normalized_text): {"username": str, "ts": float} }
recent_speech_cache = {}
recent_speech_cache_lock = threading.Lock()
recent_media_state = {}
recent_media_state_lock = threading.Lock()

REALTIME_TEXT_SCORING_ENABLED = True
REALTIME_SPEECH_DEDUP_WINDOW_SECONDS = 8.0
RECENT_MEDIA_STATE_TTL_SECONDS = 90.0
SENTENCE_SPLIT_PATTERN = re.compile(r'(?<=[。！？!?；;])\s*')
ASR_REQUIRE_VOICEPRINT_IDENTITY = False
REALTIME_ASR_VOICEPRINT_DISABLED = True
ASR_UNKNOWN_SPEAKER_LABEL = "未确认说话人"
ASR_SPEAKER_CACHE_TTL_SECONDS = 10.0    # 句子级别缓存：10秒（一句话通常不超过10秒）
ASR_SPEAKER_CACHE_MAX_HITS = 1          # 每句话只验证一次
ASR_SENTENCE_END_SILENCE_SECONDS = 3.0  # 沉默3秒视为句子结束
ASR_SELF_VOICE_GATE_ENABLED = False  # 临时禁用声纹门控，允许所有用户语音转文字
ASR_SELF_VOICE_GATE_MIN_MS = 1400
ASR_SELF_VOICE_GATE_WINDOW_MS = 2400
ASR_SELF_VOICE_GATE_CHECK_INTERVAL_MS = 700
ASR_SELF_VOICE_GATE_SILENCE_MS = 2500
ASR_SELF_VOICE_GATE_RMS_THRESHOLD = 180.0
ASR_SELF_VOICE_GATE_THRESHOLD = 0.24  # 声纹余弦距离阈值；越小越严格，避免旁人声音误归到当前账号
ASR_SELF_VOICE_GATE_FAIL_GRACE_DISTANCE = 0.27
ASR_SELF_VOICE_GATE_FAILS_TO_CLOSE = 3


def _normalize_transcript_text(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", str(text or "").strip(), flags=re.UNICODE)


def _transcript_text_similar(left: str, right: str) -> bool:
    a = _normalize_transcript_text(left)
    b = _normalize_transcript_text(right)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    ratio = SequenceMatcher(None, a, b).ratio()
    if max(len(a), len(b)) <= 8:
        return ratio >= 0.55
    if min(len(a), len(b)) < 6:
        return False
    return ratio >= 0.72


def _cleanup_recent_speech_cache(expiry_seconds: float = 15.0) -> None:
    now_ts = time.time()
    with recent_speech_cache_lock:
        expired = [k for k, v in recent_speech_cache.items() if (now_ts - v.get("ts", 0)) > expiry_seconds]
        for key in expired:
            recent_speech_cache.pop(key, None)


def _mark_recent_speech(meeting_id: int, username: str, text: str, dedup_window: float = REALTIME_SPEECH_DEDUP_WINDOW_SECONDS) -> bool:
    normalized_text = _normalize_transcript_text(text)
    if not normalized_text:
        return True

    _cleanup_recent_speech_cache()
    meeting_key = int(meeting_id)
    now_ts = time.time()

    with recent_speech_cache_lock:
        for key, cached in list(recent_speech_cache.items()):
            try:
                cached_meeting = int(key[0])
                cached_text = str(key[1])
            except Exception:
                continue
            if cached_meeting != meeting_key:
                continue
            if (now_ts - cached.get("ts", 0)) >= dedup_window:
                continue
            if _transcript_text_similar(cached_text, normalized_text):
                cached_user = cached.get("username", "")
                print(f"[DEDUP] 跳过相似重复转写: meeting={meeting_id}, first={cached_user}, skip={username}, sim_text={normalized_text[:30]}")
                return True
        recent_speech_cache[(meeting_key, normalized_text)] = {"username": username, "ts": now_ts}
    return False


def _reserve_recent_speech_by_volume(
    meeting_id: int,
    username: str,
    text: str,
    dedup_window: float = REALTIME_SPEECH_DEDUP_WINDOW_SECONDS,
    audio_volume: Optional[float] = None,
) -> Dict[str, Any]:
    normalized_text = _normalize_transcript_text(text)
    if not normalized_text:
        return {"skip": True, "reason": "empty"}

    _cleanup_recent_speech_cache()
    meeting_key = int(meeting_id)
    now_ts = time.time()
    candidate_volume = float(audio_volume or 0.0)

    with recent_speech_cache_lock:
        for key, cached in list(recent_speech_cache.items()):
            try:
                cached_meeting = int(key[0])
                cached_text = str(cached.get("normalized_text") or key[1])
            except Exception:
                continue
            if cached_meeting != meeting_key:
                continue
            if (now_ts - cached.get("ts", 0)) >= dedup_window:
                continue
            if not _transcript_text_similar(cached_text, normalized_text):
                continue

            cached_user = cached.get("username", "")
            cached_volume = float(cached.get("audio_volume") or 0.0)
            candidate_is_fuller = (
                len(normalized_text) > len(cached_text) * 1.25
                and normalized_text.find(cached_text) >= 0
            )
            louder_mic_wins = cached_user != username and candidate_volume > cached_volume * 1.18
            if candidate_is_fuller or louder_mic_wins:
                replaced = dict(cached)
                recent_speech_cache.pop(key, None)
                recent_speech_cache[(meeting_key, normalized_text)] = {
                    "username": username,
                    "text": text,
                    "normalized_text": normalized_text,
                    "ts": now_ts,
                    "audio_volume": candidate_volume,
                }
                print(
                    f"[DEDUP] replace duplicate speech: meeting={meeting_id}, fuller={candidate_is_fuller}, "
                    f"louder={louder_mic_wins}, old={cached_user}({cached_volume:.1f}), new={username}({candidate_volume:.1f})"
                )
                return {"skip": False, "replace": replaced}

            print(
                f"[DEDUP] skip duplicate by mic volume: meeting={meeting_id}, "
                f"keep={cached_user}({cached_volume:.1f}), skip={username}({candidate_volume:.1f})"
            )
            return {"skip": True, "reason": "duplicate", "winner": dict(cached)}

        recent_speech_cache[(meeting_key, normalized_text)] = {
            "username": username,
            "text": text,
            "normalized_text": normalized_text,
            "ts": now_ts,
            "audio_volume": candidate_volume,
        }
    return {"skip": False}


def _attach_recent_speech_transcript(meeting_id: int, username: str, text: str, transcript_id: int, timestamp: int) -> None:
    normalized_text = _normalize_transcript_text(text)
    if not normalized_text:
        return
    meeting_key = int(meeting_id)
    with recent_speech_cache_lock:
        for key, cached in list(recent_speech_cache.items()):
            try:
                cached_meeting = int(key[0])
            except Exception:
                continue
            if cached_meeting != meeting_key:
                continue
            cached_text = str(cached.get("normalized_text") or key[1])
            if cached.get("username") == username and _transcript_text_similar(cached_text, normalized_text):
                cached["transcript_id"] = int(transcript_id)
                cached["timestamp"] = int(timestamp)
                cached["text"] = text
                cached["ts"] = time.time()
                recent_speech_cache[key] = cached
                return


def _stage_recent_media_state_assets(
    meeting_id: int,
    username: str,
    timestamp: int,
    *,
    audio_path: str = "",
    video_path: str = "",
    snapshot_path: str = "",
) -> Dict[str, str]:
    safe_user = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(username or "user"))
    target_dir = os.path.join(ROOT_DIR, "storage", "realtime_media", str(int(meeting_id)), safe_user, str(timestamp))
    os.makedirs(target_dir, exist_ok=True)

    staged = {}
    for key, source_path in {
        "audio_path": audio_path,
        "video_path": video_path,
        "snapshot_path": snapshot_path,
    }.items():
        if not source_path or not os.path.exists(source_path):
            continue
        try:
            dest_path = os.path.join(target_dir, os.path.basename(source_path))
            shutil.copy2(source_path, dest_path)
            staged[key] = dest_path
        except Exception as e:
            print(f"[WARN] 实时媒体资产暂存失败 {key}: {e}")
    return staged


def _storage_relative_path(path_value: str) -> Optional[str]:
    if not path_value:
        return None
    try:
        abs_path = os.path.abspath(path_value)
        root = os.path.abspath(ROOT_DIR)
        if abs_path.startswith(root):
            return os.path.relpath(abs_path, root).replace("\\", "/")
    except Exception:
        pass
    return path_value.replace("\\", "/")


def _remember_recent_media_state(
    meeting_id: int,
    username: str,
    emotion_tag: str,
    body_action: str,
    audio_tone: str,
    *,
    audio_path: str = "",
    video_path: str = "",
    snapshot_path: str = "",
    video_url: str = "",
    snapshot_url: str = "",
) -> None:
    with recent_media_state_lock:
        recent_media_state[(int(meeting_id), username)] = {
            "emotion_tag": normalize_emotion_label(emotion_tag),
            "body_action": body_action or "static",
            "audio_tone": audio_tone or "",
            "audio_path": audio_path or "",
            "video_path": video_path or "",
            "snapshot_path": snapshot_path or "",
            "video_url": video_url or "",
            "snapshot_url": snapshot_url or "",
            "ts": time.time(),
        }


def _get_recent_media_state(meeting_id: int, username: str) -> Dict[str, str]:
    key = (int(meeting_id), username)
    with recent_media_state_lock:
        state = recent_media_state.get(key)
        if not state:
            return {}
        if (time.time() - state.get("ts", 0)) > RECENT_MEDIA_STATE_TTL_SECONDS:
            recent_media_state.pop(key, None)
            return {}
        return {
            "emotion_tag": state.get("emotion_tag", "neutral"),
            "body_action": state.get("body_action", "static"),
            "audio_tone": state.get("audio_tone", ""),
            "audio_path": state.get("audio_path", ""),
            "video_path": state.get("video_path", ""),
            "snapshot_path": state.get("snapshot_path", ""),
            "video_url": state.get("video_url", ""),
            "snapshot_url": state.get("snapshot_url", ""),
        }


def _split_realtime_sentences(text: str) -> List[str]:
    clean = str(text or "").strip()
    if not clean:
        return []

    sentence_split_pattern = re.compile(r"(?<=[\u3002\uff01\uff1f!?;\uff1b])\s*")
    segments = [seg.strip() for seg in sentence_split_pattern.split(clean) if seg and seg.strip()]
    if not segments:
        segments = [clean]

    normalized_segments = []
    for seg in segments:
        normalized = re.sub(r"\s+", " ", seg).strip()
        if not normalized:
            continue

        comma_parts = [part.strip() for part in re.split(r"(?<=[\uff0c,\u3001])\s*", normalized) if part and part.strip()]
        if len(normalized) >= 28 and len(comma_parts) >= 2:
            normalized_segments.extend(comma_parts)
        else:
            normalized_segments.append(normalized)

    merged_segments = []
    for seg in normalized_segments:
        if merged_segments and len(seg) <= 3 and not re.search(r"[\u3002\uff01\uff1f!?;\uff1b]$", merged_segments[-1]):
            merged_segments[-1] = f"{merged_segments[-1]}{seg}"
        else:
            merged_segments.append(seg)
    return merged_segments


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


def _select_latest_reports(reports: List[LearningReport]) -> List[LearningReport]:
    latest_reports: List[LearningReport] = []
    seen_keys = set()
    for report in reports:
        key = (int(report.meeting_id), int(report.user_id))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        latest_reports.append(report)
    return latest_reports


def _build_meeting_window_map(db: Session, meeting_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    if not meeting_ids:
        return {}

    rows = db.query(
        Transcript.meeting_id.label("meeting_id"),
        sa_func.min(Transcript.created_at).label("first_at"),
        sa_func.max(Transcript.created_at).label("last_at"),
    ).filter(
        Transcript.meeting_id.in_(meeting_ids)
    ).group_by(
        Transcript.meeting_id
    ).all()

    return {
        int(row.meeting_id): {
            "first_at": row.first_at,
            "last_at": row.last_at,
        }
        for row in rows
    }


def _build_meeting_activity_map(db: Session, meeting_ids: List[int], *, exclude_teacher: bool = True) -> Dict[int, Dict[str, int]]:
    if not meeting_ids:
        return {}

    query = db.query(
        Transcript.meeting_id.label("meeting_id"),
        sa_func.count(Transcript.id).label("speech_count"),
        sa_func.count(sa_func.distinct(Transcript.user_id)).label("member_count"),
    )
    if exclude_teacher:
        query = query.join(User, User.id == Transcript.user_id).filter(User.role != "teacher")

    rows = query.filter(
        Transcript.meeting_id.in_(meeting_ids)
    ).group_by(
        Transcript.meeting_id
    ).all()

    return {
        int(row.meeting_id): {
            "speech_count": int(row.speech_count or 0),
            "member_count": int(row.member_count or 0),
        }
        for row in rows
    }


def _build_report_metric_maps(
    db: Session,
    meeting_ids: List[int],
    user_ids: List[int],
) -> Dict[str, Dict[Any, Dict[str, Any]]]:
    if not meeting_ids or not user_ids:
        return {"by_user_id": {}, "by_username": {}, "exercise_count": {}}

    rows = db.query(
        Transcript.meeting_id.label("meeting_id"),
        Transcript.user_id.label("user_id"),
        User.username.label("username"),
        sa_func.count(Transcript.id).label("speech_count"),
        sa_func.avg(Transcript.relevance_score).label("avg_relevance"),
    ).join(
        User, User.id == Transcript.user_id
    ).filter(
        Transcript.meeting_id.in_(meeting_ids),
        Transcript.user_id.in_(user_ids),
        User.role != "teacher",
    ).group_by(
        Transcript.meeting_id,
        Transcript.user_id,
        User.username,
    ).all()

    by_user_id: Dict[Any, Dict[str, Any]] = {}
    by_username: Dict[Any, Dict[str, Any]] = {}
    for row in rows:
        avg_relevance = float(row.avg_relevance) if row.avg_relevance is not None else 0.0
        payload = {
            "speech_count": int(row.speech_count or 0),
            "avg_relevance": round(avg_relevance, 1),
        }
        by_user_id[(int(row.meeting_id), int(row.user_id))] = payload
        by_username[(int(row.meeting_id), row.username)] = payload

    return {
        "by_user_id": by_user_id,
        "by_username": by_username,
        "exercise_count": {},
    }

def update_knowledge_graph(meeting_id: int, db: Session):
    """🧠"""
    try:
        # 🧠10🧠
        transcripts = db.query(Transcript).filter(
            Transcript.meeting_id == meeting_id
        ).order_by(Transcript.id.desc()).limit(10).all()
        
        if len(transcripts) < 5:  # 🧠 5🧠
            return None
        
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()

        # 构建对话历史
        conversations = [
            {"username": t.user.username, "content": t.content}
            for t in reversed(transcripts)
        ]

        # 查询现有知识图谱
        existing_kg = db.query(KnowledgeGraph).filter(
            KnowledgeGraph.meeting_id == meeting_id
        ).first()

        existing_graph = existing_kg.graph_data if existing_kg else None

        # LLM提取新概念
        new_graph = kg_service.extract_concepts_from_conversation(
            topic=meeting.topic,
            conversations=conversations,
            existing_graph=existing_graph
        )

        if not new_graph.get("nodes"):
            return None

        # 记录发言人
        speakers = {}
        for node in new_graph.get("nodes", []):
            speakers[node["id"]] = list(set([c["username"] for c in conversations]))

        # 合并图谱
        merged_graph = kg_service.merge_graphs(existing_graph, new_graph, speakers)

        # 保存到数据库
        if existing_kg:
            existing_kg.graph_data = merged_graph
            existing_kg.updated_at = datetime.now()
        else:
            existing_kg = KnowledgeGraph(
                meeting_id=meeting_id,
                graph_data=merged_graph
            )
            db.add(existing_kg)
        
        db.commit()
        return merged_graph
        
    except Exception as e:
        print(f"知识图谱更新失败: {e}")
        return None


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
@app.get("/", response_class=HTMLResponse)
async def get_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read(), headers=NO_CACHE_HEADERS)

@app.get("/pcm-processor.js")
async def get_pcm_processor():
    return FileResponse("pcm-processor.js", media_type="application/javascript")


@app.post("/api/register")
async def register(
    student_id: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("student")
):
    """User registration"""
    try:
        print(f"[NOTE] Register request - ID: {student_id}, Role: {role}")
    except:
        print(f"[NOTE] Register request received")

    import pymssql
    try:
        conn = pymssql.connect(
            server=os.getenv("DB_HOST", ""),
            port=int(os.getenv("DB_PORT", "3433")),
            user=os.getenv("DB_USER", ""),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", ""),
            charset='utf8',
            timeout=10,
            login_timeout=10
        )
        cursor = conn.cursor()

        # Insert user
        print("[SAVE] Executing INSERT...")
        cursor.execute(
            "INSERT INTO users (student_id, username, password, role, created_at) VALUES (%s, %s, %s, %s, GETDATE())",
            (student_id, username, password, role)
        )
        conn.commit()
        cursor.close()
        conn.close()

        print(f"[OK] Registration successful")
        return {"status": "success", "message": "注册成功"}
    except pymssql.IntegrityError as e:
        print(f"[ERROR] Student ID already exists: {student_id}")
        return {"status": "error", "message": "学号/用户名已存在"}
    except Exception as e:
        error_msg = str(e)
        if "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
            print(f"[ERROR] Database connection timeout")
            return {"status": "error", "message": "数据库连接超时，请重试"}
        print(f"[ERROR] Registration failed: {e}")
        return {"status": "error", "message": f"注册失败: {error_msg}"}


@app.post("/api/login")
async def api_login(
    student_id: str = Form(...),
    password: str = Form(...)
):
    """User login"""
    print(f"[LOGIN] Login request - ID: {student_id}")

    import pymssql
    import time
    try:
        start_time = time.time()
        print(f"[DB] Connecting...")

        conn = pymssql.connect(
            server=os.getenv("DB_HOST", ""),
            port=int(os.getenv("DB_PORT", "3433")),
            user=os.getenv("DB_USER", ""),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", ""),
            charset='utf8',
            timeout=10,
            login_timeout=10
        )
        print(f"[OK] Connected: {time.time() - start_time:.2f}s")

        cursor = conn.cursor(as_dict=True)

        print("[QUERY] Querying user...")
        query_start = time.time()
        cursor.execute(
            "SELECT TOP 1 id, student_id, username, password, role FROM users WHERE student_id = %s",
            (student_id,)
        )
        user = cursor.fetchone()
        print(f"[OK] Query done: {time.time() - query_start:.2f}s")

        cursor.close()
        conn.close()

        if not user:
            print(f"[ERROR] User not found: {student_id}")
            return {"status": "error", "message": "学号/密码错误"}

        if user['password'] != password:
            print(f"[ERROR] Wrong password: {student_id}")
            return {"status": "error", "message": "密码错误"}

        total_time = time.time() - start_time
        print(f"[OK] Login success: {user['username']} ({user['role']}) - Time: {total_time:.2f}s")
        return {
            "status": "success",
            "user": {
                "id": user['id'],
                "student_id": user['student_id'],
                "username": user['username'],
                "role": user['role']
            }
        }
    except Exception as e:
        error_msg = str(e)
        print(f"[ERROR] Login failed: {error_msg}")

        if "timed out" in error_msg.lower() or "timeout" in error_msg.lower():
            return {"status": "error", "message": "数据库连接超时"}
        elif "connect" in error_msg.lower():
            return {"status": "error", "message": "无法连接数据库"}
        else:
            return {"status": "error", "message": f"登录失败: {error_msg[:100]}"}


@app.post("/login")
async def login(
    username: str = Form(...),
    class_code: str = Form(...),
    role: str = Form("student"),  # teacher/student,默认学生
    topic: str = Form(None),
    reference_materials: str = Form(None),  # JSON字符串
    material_file: UploadFile = File(None),  # 上传文件
    material_url: str = Form(None),  # 材料URL
    template_path: str = Form(None),  # 模板路径
    student_id: str = Form(None),  # 新增：用student_id查找用户，避免中文编码问题
    db: Session = Depends(get_db)
):
    """
    统一登录接口（兼容前端）
    - 学生端:加入课堂
    - 教师端:创建课堂
    """
    # 验证用户 — 优先用 student_id（纯ASCII，无编码问题）
    user = None
    if student_id:
        user = db.query(User).filter(User.student_id == student_id).first()
    if not user:
        user = db.query(User).filter(User.username == username).first()
    if not user:
        return {"status": "error", "message": "用户不存在，请先注册"}
    
    # ??
    meeting = db.query(Meeting).filter(
        Meeting.class_code == class_code, 
        Meeting.status == "active"
    ).first()
    
    if meeting:
        if str(meeting.class_code) == "100":
            kp = meeting.knowledge_points if isinstance(meeting.knowledge_points, list) else []
            trimmed = kp[:3]
            if len(kp) != len(trimmed):
                meeting.knowledge_points = trimmed
                db.commit()
        # 已存在会议，直接返回
        return {
            "status": "success",
            "meeting_id": meeting.id,
            "goals": meeting.knowledge_points,
            "topic": meeting.topic,
            "role": user.role,
            "teaching_design": meeting.teaching_design
        }
    else:
        # 创建新会议
        if role == "student":
            return {"status": "error", "message": "课堂不存在，请联系老师"}

        # 验证主题
        if not topic:
            return {"status": "error", "message": "缺少主题"}
        
        # 生成教学目标
        print(f"[AI] 生成教学目标: {topic}")

        # 收集材料
        materials = []

        # 1. 上传文件
        if material_file:
            try:
                import os
                # 创建上传目录
                upload_dir = "uploads"
                os.makedirs(upload_dir, exist_ok=True)

                # 保存文件
                file_path = os.path.join(upload_dir, material_file.filename)
                with open(file_path, "wb") as f:
                    content = await material_file.read()
                    f.write(content)

                materials.append({
                    "type": "file",
                    "filename": material_file.filename,
                    "path": file_path,
                    "size": len(content)
                })
                print(f"已保存 文件: {material_file.filename}")
            except Exception as e:
                print(f"[ERROR] 文件上传失败: {e}")

        # 2. 添加URL
        if material_url:
            materials.append({
                "type": "url",
                "url": material_url
            })
            print(f"[DB] 添加URL: {material_url}")

        # 3. 处理reference_materials参数（兼容旧版）
        if reference_materials:
            try:
                old_materials = json.loads(reference_materials)
                if isinstance(old_materials, list):
                    materials.extend(old_materials)
                else:
                    materials.append(old_materials)
            except:
                materials.append({"type": "text", "content": reference_materials})

        # 调用LLM生成目标
        print(f"[AI] AI生成目标: {topic}")
        try:
            goals = llm.init_meeting_goals(topic)
            if not goals or len(goals) == 0:
                goals = [
                    {"id": 1, "desc": "理解基本概念", "status": "pending"},
                    {"id": 2, "desc": "掌握核心方法", "status": "pending"},
                    {"id": 3, "desc": "应用实践练习", "status": "pending"}
                ]
                print("[WARN] LLM返回空，使用默认目标")
            else:
                print(f"[OK] 生成了 {len(goals)} 个目标")
        except Exception as e:
            print(f"[ERROR] LLM生成失败: {e}, 使用默认")
            goals = [
                {"id": 1, "desc": "理解基本概念", "status": "pending"},
                {"id": 2, "desc": "掌握核心方法", "status": "pending"},
                {"id": 3, "desc": "应用实践练习", "status": "pending"}
            ]

        # 生成教学设计（可选）
        teaching_design = {
            "objectives": [g["desc"] for g in goals],
            "phases": [
                {"phase_name": "导入阶段", "duration": 10, "tasks": ["激活先验知识", "引入主题"]},
                {"phase_name": "探究阶段", "duration": 25, "tasks": ["小组讨论", "实践操作"]},
                {"phase_name": "总结阶段", "duration": 10, "tasks": ["归纳总结", "反思评价"]}
            ],
            "division_strategy": {
                "roles": ["记录员", "发言人", "协调员"],
                "responsibilities": "明确分工，协作完成"
            },
            "evaluation_criteria": ["参与度", "贡献度", "协作能力"]
        }

        # 创建会议
        meeting = Meeting(
            class_code=class_code,
            teacher_id=user.id,
            topic=topic,
            reference_materials=materials if materials else None,
            teaching_design=teaching_design,
            knowledge_points=goals,
            template_path=template_path  # 保存模板路径
        )
        db.add(meeting)
        db.commit()
        db.refresh(meeting)

        return {
            "status": "success",
            "meeting_id": meeting.id,
            "goals": meeting.knowledge_points,
            "topic": meeting.topic,
            "role": user.role,
            "teaching_design": teaching_design,
            "message": "课堂创建成功"
        }


@app.get("/summary")
async def get_summary(meeting_id: int, db: Session = Depends(get_db)):
    transcripts = db.query(Transcript).filter(Transcript.meeting_id == meeting_id).all()
    emotions = db.query(EmotionLog).filter(EmotionLog.meeting_id == meeting_id).all()
    emo_stats = {}
    for e in emotions:
        emotion_key = normalize_emotion_label(e.emotion_type)
        emo_stats[emotion_key] = emo_stats.get(emotion_key, 0) + 1
    full_text = "\n".join([f"{t.user.username}: {t.content}" for t in transcripts])
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    return llm.analyze_emotion_and_summary(meeting.topic, full_text, emo_stats)


@app.get("/api/knowledge-graph/{meeting_id}")
async def get_knowledge_graph(meeting_id: int, db: Session = Depends(get_db)):
    """获取知识图谱"""
    kg = db.query(KnowledgeGraph).filter(KnowledgeGraph.meeting_id == meeting_id).first()
    if not kg:
        return {"status": "empty", "data": {"nodes": [], "edges": []}}

    # 生成可视化数据
    viz_data = kg_service.generate_graph_visualization_data(kg.graph_data)
    return {"status": "success", "data": viz_data}


@app.get("/api/meeting/{meeting_id}")
async def get_meeting(meeting_id: int, db: Session = Depends(get_db)):
    """获取课堂信息（包括目标）"""
    meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
    if not meeting:
        return {"status": "error", "message": "课堂不存在"}

    return {
        "status": "success",
        "meeting_id": meeting.id,
        "topic": meeting.topic,
        "goals": meeting.knowledge_points or [],
        "teaching_design": meeting.teaching_design
    }


@app.get("/api/transcripts/{meeting_id}")
async def get_transcripts(meeting_id: int, limit: int = 500, db: Session = Depends(get_db)):
    """获取课堂历史发言（用于前端对话栏展示）"""
    try:
        limit = max(1, min(int(limit), 2000))
        transcripts = db.query(Transcript).options(joinedload(Transcript.user)).filter(
            Transcript.meeting_id == meeting_id
        ).order_by(Transcript.created_at.asc()).limit(limit).all()

        items = []
        for t in transcripts:
            # 课堂对话历史只展示学生发言（不包含老师）
            if getattr(t.user, "role", None) == "teacher":
                continue
            ts = t.created_at or t.timestamp
            items.append({
                "id": t.id,
                "username": t.user.username if t.user else "",
                "text": t.content,
                "timestamp": int(ts.timestamp() * 1000) if ts else None,
                "quality_score": getattr(t, "quality_score", None),
                "quality_feedback": getattr(t, "quality_feedback", None),
                "emotion": getattr(t, "emotion_tag", None),
                "action": getattr(t, "body_action", None),
            })

        return {"status": "success", "transcripts": items}
    except Exception as e:
        print(f"[ERROR] 获取课堂发言失败: {e}")
        return {"status": "error", "message": str(e)}


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


@app.get("/api/research-runtime")
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


@app.post("/api/research-runtime/config")
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


@app.post("/api/research-runtime/prepare-layout")
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


@app.post("/api/generate-report")
async def generate_learning_report(
    meeting_id: int = Form(...),
    user_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """生成学习报告（按上次报告后的新发言生成，保留历史版本）"""
    try:
        # 最近一次报告（用于截断“本轮课堂发言窗口”）
        last_report = db.query(LearningReport).filter(
            LearningReport.meeting_id == meeting_id,
            LearningReport.user_id == user_id
        ).order_by(LearningReport.created_at.desc()).first()
        cutoff_time = last_report.created_at if last_report else None

        # 查询数据
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        user = db.query(User).filter(User.id == user_id).first()

        if not meeting or not user:
            return {"status": "error", "message": "课堂或用户不存在"}

        # 获取“本轮课堂窗口”数据（上次报告之后）
        transcript_query = db.query(Transcript).filter(Transcript.meeting_id == meeting_id)
        emotion_query = db.query(EmotionLog).filter(EmotionLog.meeting_id == meeting_id)
        if cutoff_time:
            transcript_query = transcript_query.filter(Transcript.created_at > cutoff_time)
            emotion_query = emotion_query.filter(EmotionLog.created_at > cutoff_time)

        all_transcripts = transcript_query.order_by(Transcript.id).all()
        all_emotions = emotion_query.all()

        # 报告生成只面向学生：过滤掉教师账号相关数据，避免教师被纳入学习报告
        student_transcripts = [t for t in all_transcripts if getattr(t.user, "role", None) != "teacher"]
        student_emotions = [e for e in all_emotions if getattr(e.user, "role", None) != "teacher"]

        # 统计个人数据
        user_transcripts = [t for t in student_transcripts if t.user_id == user_id]
        speech_count = len(user_transcripts)
        avg_relevance = (
            sum([t.relevance_score or 0 for t in user_transcripts]) / speech_count
            if speech_count > 0 else 0
        )

        print(f"[STATS] 报告生成 - 用户名:{user.username}, user_id:{user_id}, 发言数:{speech_count}, 总发言:{len(all_transcripts)}")

        # 如果没找到，按用户名查找
        if speech_count == 0:
            user_transcripts = [t for t in student_transcripts if t.user.username == user.username]
            speech_count = len(user_transcripts)
            avg_relevance = (
                sum([t.relevance_score or 0 for t in user_transcripts]) / speech_count
                if speech_count > 0 else 0
            )
            print(f"[STATS] 按用户名查找 - 发言数:{speech_count}")

        # 本轮无学生发言，不生成新报告（避免空报告覆盖体验）
        if speech_count == 0:
            return {
                "status": "no_new_data",
                "message": "本次课堂无你的新发言，未生成新报告"
            }

        user_emotions = [e for e in student_emotions if e.user_id == user_id]
        emotion_stats = {}
        for e in user_emotions:
            emotion_key = normalize_emotion_label(e.emotion_type)
            emotion_stats[emotion_key] = emotion_stats.get(emotion_key, 0) + 1

        # 构建全课堂数据（供LLM分析）
        all_transcripts_data = [{
            "username": t.user.username,
            "content": t.content,
            "timestamp": t.created_at.isoformat()
        } for t in student_transcripts]

        # 统计所有学生表现（供LLM对比）
        students = db.query(User).join(Transcript).filter(
            Transcript.meeting_id == meeting_id,
            User.role != "teacher"
        ).distinct().all()

        student_performances = []
        for s in students:
            s_transcripts = [t for t in student_transcripts if t.user_id == s.id]
            s_count = len(s_transcripts)
            s_relevance = (
                sum([(t.relevance_score or 0) for t in s_transcripts]) / s_count
                if s_count > 0 else 0
            )
            student_performances.append({
                "username": s.username,
                "speech_count": s_count,
                "avg_relevance": round(s_relevance, 2)
            })

        all_emotion_stats = {}
        for e in student_emotions:
            emotion_key = normalize_emotion_label(e.emotion_type)
            all_emotion_stats[emotion_key] = all_emotion_stats.get(emotion_key, 0) + 1

        # 调用LLM生成报告
        print("[AI] 生成课程报告...")
        course_report = llm.generate_course_report(
            meeting_topic=meeting.topic,
            all_transcripts=all_transcripts_data,
            emotion_stats=all_emotion_stats,
            student_performances=student_performances
        )
        if research_runtime.research_algorithms_active:
            course_report = research_runtime.enrich_course_report(
                meeting_topic=meeting.topic,
                all_transcripts=all_transcripts_data,
                emotion_stats=all_emotion_stats,
                student_performances=student_performances,
                course_report=course_report,
            )

        # 提取学生评价
        student_review = None
        for review in course_report.get("student_reviews", []):
            if review.get("student_name") == user.username:
                student_review = review
                break

        if not student_review:
            student_review = {
                "strengths": [],
                "weaknesses": [],
                "unmastered_concepts": [],
                "suggestions": "继续保持，积极参与"
            }

        # 确保 basic_info.members 存在
        members_list = list(set([t.user.username for t in student_transcripts]))
        basic_info = course_report.get("basic_info") or {}
        if not basic_info.get("members") or not isinstance(basic_info.get("members"), list):
            basic_info = {
                **basic_info,
                "topic": meeting.topic,
                "members": members_list,
                "recorder": basic_info.get("recorder", "课程助手")
            }

        # 构建报告数据
        report_data = {
            "student_name": user.username,
            "meeting_topic": meeting.topic,
            "speech_count": speech_count,
            "avg_relevance": round(avg_relevance, 2),
            "emotion_stats": emotion_stats,
            "strengths": student_review.get("strengths", []),
            "weaknesses": student_review.get("weaknesses", []),
            "unmastered_concepts": student_review.get("unmastered_concepts", []),
            "improvement_suggestions": student_review.get("suggestions", ""),
            "course_summary": course_report.get("summary", ""),
            "discussion_process": course_report.get("discussion_process", ""),
            "key_findings": course_report.get("key_findings", []),
            "class_atmosphere": course_report.get("class_atmosphere", ""),
            "summary": course_report.get("summary", ""),
            "basic_info": basic_info,
            "core_questions": course_report.get("core_questions", []),
            "viewpoints": course_report.get("viewpoints", []),
            "highlights": course_report.get("highlights") or {},
            "consensus": course_report.get("consensus", []),
            "unresolved": course_report.get("unresolved") or {},
            "action_plan": course_report.get("action_plan") or {},
            "student_reviews": course_report.get("student_reviews", []),
        }
        if research_runtime.research_algorithms_active:
            report_data["ipa_profile"] = student_review.get("ipa_profile", {})
            report_data["diagnostic_tags"] = student_review.get("diagnostic_tags", [])
            report_data["research"] = course_report.get("research", {})

        print(f"[DEBUG] 报告数据: speech_count={report_data['speech_count']}, avg_relevance={report_data['avg_relevance']}")

        # 保存新报告（保留历史版本，不覆盖）
        report = LearningReport(
            meeting_id=meeting_id,
            user_id=user_id,
            report_data=report_data
        )
        db.add(report)
        db.commit()
        db.refresh(report)

        # 生成练习题（基于薄弱点）
        unmastered = "; ".join(student_review.get("unmastered_concepts", []))
        if not unmastered:
            unmastered = "基础知识：" + meeting.topic

        exercises_result = llm.generate_exercises(unmastered, meeting.topic)
        exercises_list = exercises_result.get("exercises", [])

        # 保存练习题
        for ex in exercises_list:
            exercise = Exercise(
                report_id=report.id,
                question=ex.get("question"),
                question_type=ex.get("type"),
                options=ex.get("options"),
                answer=ex.get("answer"),
                knowledge_tag=ex.get("knowledge_tag"),
                difficulty=ex.get("difficulty", 0.5),
                estimated_time=ex.get("estimated_time", 5)
            )
            db.add(exercise)

        db.commit()

        return {
            "status": "success",
            "report": report_data,
            "exercises": exercises_list,
            "cached": False,
            "regenerated": True if last_report else False
        }

    except Exception as e:
        print(f"报告生成失败: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


@app.get("/api/reports/{user_id}")
async def get_user_reports(user_id: int, db: Session = Depends(get_db)):
    """获取用户的所有报告"""
    reports = db.query(LearningReport).filter(LearningReport.user_id == user_id).order_by(LearningReport.created_at.desc()).all()
    result = []
    for r in reports:
        meeting = db.query(Meeting).filter(Meeting.id == r.meeting_id).first()
        exercise_count = db.query(Exercise).filter(Exercise.report_id == r.id).count()
        result.append({
            "report_id": r.id,
            "meeting_id": r.meeting_id,
            "class_code": meeting.class_code if meeting else "",
            "data": r.report_data,
            "exercise_count": exercise_count,
            "created_at": r.created_at.isoformat()
        })
    return {
        "status": "success",
        "reports": result
    }


# 新增接口: 获取某次课堂的所有学生报告
@app.get("/api/meeting-reports/{meeting_id}")
async def get_meeting_reports(meeting_id: int, db: Session = Depends(get_db)):
    """获取课堂的所有学生报告"""
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        reports = db.query(LearningReport).filter(
            LearningReport.meeting_id == meeting_id
        ).order_by(LearningReport.created_at.desc()).all()
        latest_reports = _select_latest_reports(reports)

        user_ids = sorted({int(r.user_id) for r in latest_reports})
        users = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
        user_map = {int(user.id): user for user in users}

        metric_maps = _build_report_metric_maps(db, [meeting_id], user_ids)
        by_user_id = metric_maps["by_user_id"]
        by_username = metric_maps["by_username"]

        result = []
        for report in latest_reports:
            user = user_map.get(int(report.user_id))
            if not user or user.role == "teacher":
                continue

            data = report.report_data or {}
            metrics = by_user_id.get((int(report.meeting_id), int(report.user_id))) or by_username.get((int(report.meeting_id), user.username)) or {}
            result.append({
                "report_id": report.id,
                "meeting_id": report.meeting_id,
                "user_id": report.user_id,
                "class_code": meeting.class_code if meeting else "",
                "student_id": user.student_id,
                "student_name": user.username,
                "speech_count": int(metrics.get("speech_count", 0) or data.get("speech_count", 0)),
                "avg_relevance": metrics.get("avg_relevance", data.get("avg_relevance", 0)),
                "improvement_suggestions": data.get("improvement_suggestions", ""),
                "summary": data.get("course_summary", "")[:100] + "..." if data.get("course_summary") else "",
                "created_at": report.created_at.isoformat()
            })
        
        return {
            "status": "success",
            "reports": result
        }
    except Exception as e:
        print(f"[ERROR] ??: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


# === WebSocket 连接管理器 (房间隔离) ===
class ConnectionManager:
    def __init__(self):
        self.active = []  # 所有连接
        self.meeting_connections = {}  # {meeting_id: {username: websocket}}
        self.last_speech_time = {}  # {meeting_id: timestamp} 最后发言时间
        self.speech_counts = {}  # {meeting_id: {username: count}} 发言计数
        self.silence_notified = {}  # {meeting_id: bool} 是否已通知沉默
        self.vote_confirmations = {}  # {vote_id: set(username)} 投票确认追踪

    async def connect(self, ws, meeting_id, username):
        await ws.accept()
        self.active.append(ws)
        if meeting_id not in self.meeting_connections:
            self.meeting_connections[meeting_id] = {}
        self.meeting_connections[meeting_id][username] = ws

    def disconnect(self, ws, meeting_id, username):
        if ws in self.active:
            self.active.remove(ws)
        if meeting_id in self.meeting_connections:
            if username in self.meeting_connections[meeting_id]:
                del self.meeting_connections[meeting_id][username]

    async def broadcast(self, msg):
        for cx in self.active:
            try:
                await cx.send_json(msg)
            except:
                pass

    async def broadcast_to_meeting(self, meeting_id, msg):
        """向指定课堂的所有成员广播消息"""
        if meeting_id not in self.meeting_connections:
            print(f"[WARN] 课堂{meeting_id}无连接")
            return

        print(f"[SEND] 广播到课堂{meeting_id}: {msg.get('type', 'unknown')}")
        success_count = 0
        fail_count = 0

        for username, ws in self.meeting_connections[meeting_id].items():
            try:
                await ws.send_json(msg)
                success_count += 1
                print(f"  [OK] 发送成功: {username}")
            except Exception as e:
                fail_count += 1
                print(f"  [ERROR] 发送失败: {username} - {type(e).__name__}: {e}")

        print(f"[STATS] 广播完成: 成功{success_count}, 失败{fail_count}")

    def get_online_members(self, meeting_id):
        """获取课堂在线成员列表"""
        if meeting_id in self.meeting_connections:
            return list(self.meeting_connections[meeting_id].keys())
        return []

    async def send_to_user(self, meeting_id, username, msg):
        """向指定课堂的指定用户发送消息"""
        if meeting_id in self.meeting_connections:
            ws = self.meeting_connections[meeting_id].get(username)
            if ws:
                try:
                    await ws.send_json(msg)
                except Exception as e:
                    print(f"[ERROR] 发送给{username}失败: {e}")

    def record_speech(self, meeting_id, username):
        """记录发言，更新计数和时间"""
        import time as _time
        self.last_speech_time[meeting_id] = _time.time()
        self.silence_notified[meeting_id] = False
        if meeting_id not in self.speech_counts:
            self.speech_counts[meeting_id] = {}
        self.speech_counts[meeting_id][username] = self.speech_counts[meeting_id].get(username, 0) + 1

    def get_quiet_members(self, meeting_id, threshold=2):
        """获取发言明显偏少的在线成员（相对比较）
        触发条件：
        1. 所有其他成员都已发言，该成员却0发言
        2. 该成员发言次数 < 其他成员平均发言次数的 30%
        3. 兜底：发言次数 < threshold（绝对阈值）且其他人都已超过
        """
        online = self.get_online_members(meeting_id)
        if len(online) < 2:
            return []
        counts = self.speech_counts.get(meeting_id, {})
        quiet = []
        all_counts = [counts.get(m, 0) for m in online]
        total_speeches = sum(all_counts)
        if total_speeches == 0:
            return []  # 没人发言过，不触发

        for m in online:
            my_count = counts.get(m, 0)
            others = [counts.get(o, 0) for o in online if o != m]
            others_avg = sum(others) / len(others) if others else 0
            all_others_spoken = all(c > 0 for c in others)

            # 条件1：其他人都发言了，自己0发言
            if my_count == 0 and all_others_spoken:
                quiet.append(m)
            # 条件2：自己发言次数 < 其他人平均的30%（且其他人平均>=3）
            elif others_avg >= 3 and my_count < others_avg * 0.3:
                quiet.append(m)
        return quiet

    def is_group_silent(self, meeting_id, silence_seconds=120):
        """检查课堂是否沉默超过指定秒数"""
        import time as _time
        last = self.last_speech_time.get(meeting_id)
        if last is None:
            return False
        return (_time.time() - last) >= silence_seconds


manager = ConnectionManager()


# === WebRTC 信令（仅转发 JSON，不处理 SDP）===
class SignalConnectionManager:
    """按课堂隔离，将 offer/answer/ICE 点对点转发给目标用户。"""

    def __init__(self):
        self.meeting_connections = {}  # {meeting_id: {username: WebSocket}}

    async def register(self, websocket: WebSocket, meeting_id: int, username: str):
        await websocket.accept()
        if meeting_id not in self.meeting_connections:
            self.meeting_connections[meeting_id] = {}
        self.meeting_connections[meeting_id][username] = websocket

    def unregister(self, meeting_id: int, username: str):
        if meeting_id in self.meeting_connections and username in self.meeting_connections[meeting_id]:
            del self.meeting_connections[meeting_id][username]

    async def forward_to(self, meeting_id: int, target_username: str, msg: dict) -> bool:
        ws = self.meeting_connections.get(meeting_id, {}).get(target_username)
        if not ws:
            return False
        try:
            await ws.send_json(msg)
            return True
        except Exception:
            return False


signal_manager = SignalConnectionManager()


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

        from ai_core import RealtimeTranscriber

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


@app.get("/api/exercises/{report_id}")
async def get_exercises(report_id: int, db: Session = Depends(get_db)):
    """获取报告对应的习题列表（JSON格式）"""
    exercises = db.query(Exercise).filter(Exercise.report_id == report_id).all()
    return {
        "status": "success",
        "exercises": [
            {
                "id": ex.id,
                "question": ex.question,
                "type": ex.question_type,
                "options": ex.options,
                "answer": ex.answer,
                "knowledge_tag": ex.knowledge_tag,
                "difficulty": ex.difficulty,
                "estimated_time": ex.estimated_time
            }
            for ex in exercises
        ]
    }


@app.post("/api/generate-report-stream")
async def generate_report_stream(
    meeting_id: int = Form(...),
    user_id: int = Form(...),
):
    """流式生成学习报告 - SSE进度推送"""
    import json as _json

    def generate():
        db = SessionLocal()
        try:
            yield f"data: {_json.dumps({'type': 'progress', 'message': '正在分析课堂数据...'}, ensure_ascii=False)}\n\n"

            last_report = db.query(LearningReport).filter(
                LearningReport.meeting_id == meeting_id,
                LearningReport.user_id == user_id
            ).order_by(LearningReport.created_at.desc()).first()
            cutoff_time = last_report.created_at if last_report else None

            meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
            user = db.query(User).filter(User.id == user_id).first()

            if not meeting or not user:
                yield f"data: {_json.dumps({'type': 'error', 'message': '课堂或用户不存在'}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return

            transcript_query = db.query(Transcript).filter(Transcript.meeting_id == meeting_id)
            emotion_query = db.query(EmotionLog).filter(EmotionLog.meeting_id == meeting_id)
            if cutoff_time:
                transcript_query = transcript_query.filter(Transcript.created_at > cutoff_time)
                emotion_query = emotion_query.filter(EmotionLog.created_at > cutoff_time)

            all_transcripts = transcript_query.order_by(Transcript.id).all()
            all_emotions = emotion_query.all()

            student_transcripts = [t for t in all_transcripts if getattr(t.user, "role", None) != "teacher"]
            student_emotions = [e for e in all_emotions if getattr(e.user, "role", None) != "teacher"]

            user_transcripts = [t for t in student_transcripts if t.user_id == user_id]
            speech_count = len(user_transcripts)
            avg_relevance = (
                sum([t.relevance_score or 0 for t in user_transcripts]) / speech_count
                if speech_count > 0 else 0
            )

            if speech_count == 0:
                user_transcripts = [t for t in student_transcripts if t.user.username == user.username]
                speech_count = len(user_transcripts)
                avg_relevance = (
                    sum([t.relevance_score or 0 for t in user_transcripts]) / speech_count
                    if speech_count > 0 else 0
                )

            if speech_count == 0:
                yield f"data: {_json.dumps({'type': 'error', 'message': '本次课堂无你的新发言，未生成新报告'}, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return

            yield f"data: {_json.dumps({'type': 'progress', 'message': f'已找到 {speech_count} 条发言记录，正在生成AI报告...'}, ensure_ascii=False)}\n\n"

            user_emotions = [e for e in student_emotions if e.user_id == user_id]
            emotion_stats = {}
            for e in user_emotions:
                emotion_key = normalize_emotion_label(e.emotion_type)
                emotion_stats[emotion_key] = emotion_stats.get(emotion_key, 0) + 1

            all_transcripts_data = [{
                "username": t.user.username,
                "content": t.content,
                "timestamp": t.created_at.isoformat()
            } for t in student_transcripts]

            students = db.query(User).join(Transcript).filter(
                Transcript.meeting_id == meeting_id,
                User.role != "teacher"
            ).distinct().all()

            student_performances = []
            for s in students:
                s_transcripts = [t for t in student_transcripts if t.user_id == s.id]
                s_count = len(s_transcripts)
                s_relevance = (
                    sum([(t.relevance_score or 0) for t in s_transcripts]) / s_count
                    if s_count > 0 else 0
                )
                student_performances.append({
                    "username": s.username,
                    "speech_count": s_count,
                    "avg_relevance": round(s_relevance, 2)
                })

            all_emotion_stats = {}
            for e in student_emotions:
                emotion_key = normalize_emotion_label(e.emotion_type)
                all_emotion_stats[emotion_key] = all_emotion_stats.get(emotion_key, 0) + 1

            # LLM生成报告
            course_report = llm.generate_course_report(
                meeting_topic=meeting.topic,
                all_transcripts=all_transcripts_data,
                emotion_stats=all_emotion_stats,
                student_performances=student_performances
            )
            if research_runtime.research_algorithms_active:
                course_report = research_runtime.enrich_course_report(
                    meeting_topic=meeting.topic,
                    all_transcripts=all_transcripts_data,
                    emotion_stats=all_emotion_stats,
                    student_performances=student_performances,
                    course_report=course_report,
                )

            yield f"data: {_json.dumps({'type': 'progress', 'message': '报告生成完毕，正在生成针对性习题...'}, ensure_ascii=False)}\n\n"

            student_review = None
            for review in course_report.get("student_reviews", []):
                if review.get("student_name") == user.username:
                    student_review = review
                    break

            if not student_review:
                student_review = {
                    "strengths": [],
                    "weaknesses": [],
                    "unmastered_concepts": [],
                    "suggestions": "继续保持，积极参与"
                }

            members_list = list(set([t.user.username for t in student_transcripts]))
            basic_info = course_report.get("basic_info") or {}
            if not basic_info.get("members") or not isinstance(basic_info.get("members"), list):
                basic_info = {
                    **basic_info,
                    "topic": meeting.topic,
                    "members": members_list,
                    "recorder": basic_info.get("recorder", "课程助手")
                }

            report_data = {
                "student_name": user.username,
                "meeting_topic": meeting.topic,
                "speech_count": speech_count,
                "avg_relevance": round(avg_relevance, 2),
                "emotion_stats": emotion_stats,
                "strengths": student_review.get("strengths", []),
                "weaknesses": student_review.get("weaknesses", []),
                "unmastered_concepts": student_review.get("unmastered_concepts", []),
                "improvement_suggestions": student_review.get("suggestions", ""),
                "course_summary": course_report.get("summary", ""),
                "discussion_process": course_report.get("discussion_process", ""),
                "key_findings": course_report.get("key_findings", []),
                "class_atmosphere": course_report.get("class_atmosphere", ""),
                "summary": course_report.get("summary", ""),
                "basic_info": basic_info,
                "core_questions": course_report.get("core_questions", []),
                "viewpoints": course_report.get("viewpoints", []),
                "highlights": course_report.get("highlights") or {},
                "consensus": course_report.get("consensus", []),
                "unresolved": course_report.get("unresolved") or {},
                "action_plan": course_report.get("action_plan") or {},
                "student_reviews": course_report.get("student_reviews", []),
            }
            if research_runtime.research_algorithms_active:
                report_data["ipa_profile"] = student_review.get("ipa_profile", {})
                report_data["diagnostic_tags"] = student_review.get("diagnostic_tags", [])
                report_data["research"] = course_report.get("research", {})

            report = LearningReport(
                meeting_id=meeting_id,
                user_id=user_id,
                report_data=report_data
            )
            db.add(report)
            db.commit()
            db.refresh(report)

            # 生成习题
            unmastered = "; ".join(student_review.get("unmastered_concepts", []))
            if not unmastered:
                unmastered = "基础知识：" + meeting.topic

            exercises_result = llm.generate_exercises(unmastered, meeting.topic)
            exercises_list = exercises_result.get("exercises", [])

            for ex in exercises_list:
                exercise = Exercise(
                    report_id=report.id,
                    question=ex.get("question"),
                    question_type=ex.get("type"),
                    options=ex.get("options"),
                    answer=ex.get("answer"),
                    knowledge_tag=ex.get("knowledge_tag"),
                    difficulty=ex.get("difficulty", 0.5),
                    estimated_time=ex.get("estimated_time", 5)
                )
                db.add(exercise)
            db.commit()

            yield f"data: {_json.dumps({'type': 'progress', 'message': f'习题生成完毕！共 {len(exercises_list)} 道题'}, ensure_ascii=False)}\n\n"

            # 最终结果
            yield f"data: {_json.dumps({'type': 'complete', 'report': report_data, 'exercises': exercises_list, 'report_id': report.id}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            print(f"[OK] 流式报告生成完毕: speech_count={speech_count}, exercises={len(exercises_list)}")

        except Exception as e:
            print(f"[ERROR] 流式报告生成失败: {e}")
            import traceback
            traceback.print_exc()
            yield f"data: {_json.dumps({'type': 'error', 'message': f'报告生成失败: {str(e)}'}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            db.close()

    return StreamingResponse(generate(), media_type="text/event-stream")


# ===== 声网 Agora Token 生成 =====
DEFAULT_AGORA_APP_ID = "d3144900be6843d8a8c14271f1da8cdb"


def _normalize_agora_auth_mode(value: Optional[str]) -> str:
    raw = (value or "").strip().lower()
    if raw in ("appid", "app_id", "static", "null", "none", "no_token"):
        return "appid"
    if raw in ("token", "dynamic", "certificate", "app_certificate"):
        return "token"
    return "auto"


def _get_agora_rtc_config():
    app_id = (os.getenv("AGORA_APP_ID") or DEFAULT_AGORA_APP_ID).strip()
    app_certificate = (os.getenv("AGORA_APP_CERTIFICATE") or "").strip()
    configured_mode = _normalize_agora_auth_mode(os.getenv("AGORA_AUTH_MODE"))
    auth_mode = configured_mode if configured_mode != "auto" else ("token" if app_certificate else "appid")

    config = {
        "app_id": app_id,
        "app_certificate": app_certificate,
        "auth_mode": auth_mode,
        "use_token": auth_mode == "token",
    }

    if not app_id:
        config["error"] = "Agora App ID 未配置"
    elif auth_mode == "token" and not app_certificate:
        config["error"] = "Agora 当前配置为动态 Token 模式，但服务端未配置 AGORA_APP_CERTIFICATE"

    return config

@app.get("/api/agora-token")
async def get_agora_token(channel: str, uid: str = "0", _: Optional[str] = None, response: Response = None):
    """返回前端加入声网频道所需的 RTC 配置与 Token（如启用）。"""
    if response is not None:
        for key, value in NO_CACHE_HEADERS.items():
            response.headers[key] = value

    agora_config = _get_agora_rtc_config()
    response = {
        "appId": agora_config["app_id"],
        "authMode": agora_config["auth_mode"],
        "useToken": agora_config["use_token"],
        "token": None,
    }

    if agora_config.get("error"):
        response["error"] = agora_config["error"]
        return response

    if not agora_config["use_token"]:
        return response

    try:
        from agora_token_builder import RtcTokenBuilder
        import time as _time

        expire_seconds = 86400  # 24小时
        current_ts = int(_time.time())
        privilege_expired_ts = current_ts + expire_seconds
        # 使用 buildTokenWithAccount 支持字符串UID
        token = RtcTokenBuilder.buildTokenWithAccount(
            agora_config["app_id"], agora_config["app_certificate"],
            channel, uid, 1, privilege_expired_ts
        )
        response["token"] = token
        response["expireAt"] = privilege_expired_ts
        return response
    except ModuleNotFoundError as e:
        print(f"[ERROR] Agora token 依赖缺失: {e}")
        response["error"] = "服务器缺少 agora_token_builder 依赖，请安装后重试"
        return response
    except Exception as e:
        print(f"[ERROR] 生成Agora Token失败: {e}")
        response["error"] = f"生成Agora Token失败: {str(e)}"
        return response


@app.post("/api/end-class")
async def end_class(
    meeting_id: int = Form(...),
    username: str = Form(...),
    db: Session = Depends(get_db)
):
    """教师结束课堂"""
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"status": "error", "message": "课堂不存在"}

        # 验证是教师
        user = db.query(User).filter(User.student_id == username).first()
        if not user or user.role != "teacher":
            return {"status": "error", "message": "只有教师可以结束课堂"}

        # 更新课堂状态
        meeting.status = "ended"
        db.commit()

        # 广播课堂结束通知到所有在线成员
        await manager.broadcast_to_meeting(meeting_id, {
            "type": "class_ended",
            "message": "教师已结束本次课堂",
            "teacher": user.username
        })

        # 断开所有成员的WebSocket连接
        if meeting_id in manager.meeting_connections:
            for member_ws in list(manager.meeting_connections[meeting_id].values()):
                try:
                    await member_ws.close()
                except:
                    pass
            manager.meeting_connections.pop(meeting_id, None)

        print(f"[OK] 课堂 {meeting_id} 已被教师 {username} 结束")
        return {"status": "success", "message": "课堂已结束"}
    except Exception as e:
        print(f"[ERROR] end-class: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/suggest-topic")
async def suggest_topic(meeting_id: int = Form(...), db: Session = Depends(get_db)):
    """当学生说'不知道该说什么'时，AI自动总结当前情况并推送话题建议"""
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"status": "error", "message": "会议不存在"}

        # 获取最近的发言记录
        recent = db.query(Transcript).filter(
            Transcript.meeting_id == meeting_id
        ).order_by(Transcript.created_at.desc()).limit(15).all()

        transcripts_text = "\n".join([f"{t.user.username}: {t.content}" for t in recent if t.content]) if recent else "暂无发言"

        # 获取当前目标
        goals = meeting.knowledge_points or []
        goals_text = "\n".join([f"- {g.get('desc', '')} ({g.get('status', 'pending')})" for g in goals[:8]]) if goals else "暂无目标"

        prompt = f"""你是课堂讨论助手。学生们在讨论中遇到了瓶颈，不知道接下来该讨论什么。

课程主题：{meeting.topic}
当前教学目标：
{goals_text}

最近课堂发言：
{transcripts_text}

请根据以上信息：
1. 简要总结目前的讨论进展（1句话）
2. 提出2-3个具体的、有启发性的讨论话题或问题，帮助学生继续深入讨论

要求：话题要具体、有针对性，能激发思考。总字数不超过150字。直接输出内容，不要加标题。"""

        result = llm.client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300
        )
        suggestion = result.choices[0].message.content.strip()
        return {"status": "success", "suggestion": suggestion}
    except Exception as e:
        print(f"[ERROR] suggest-topic: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/quick-decompose")
async def quick_decompose(
    meeting_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """一键分解：跳过聚类投票，直接分析发言并生成子任务"""
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"status": "error", "message": "课堂不存在"}

        transcripts = db.query(Transcript).filter(
            Transcript.meeting_id == meeting_id
        ).order_by(Transcript.id).all()

        if len(transcripts) < 1:
            return {"status": "error", "message": "暂无发言记录"}

        all_transcripts = [{
            "username": t.user.username,
            "content": t.content
        } for t in transcripts]

        # 一次 LLM 调用完成分析+分解
        result = llm.quick_decompose(
            all_transcripts, meeting.topic, meeting.knowledge_points or []
        )

        # 更新目标列表
        new_goals = list(meeting.knowledge_points or [])
        for sg in result.get("sub_goals", []):
            new_goals.append({
                "id": len(new_goals) + 1,
                "desc": f"[深入探讨] {sg['desc']}",
                "status": "pending",
                "parent_viewpoint": result.get("main_viewpoint", "")
            })
        meeting.knowledge_points = new_goals
        db.commit()

        # 广播更新到所有客户端
        await manager.broadcast_to_meeting(meeting_id, {
            "type": "goals_updated",
            "updated_goals": meeting.knowledge_points,
            "main_viewpoint": result.get("main_viewpoint", ""),
            "sub_goals": result.get("sub_goals", []),
            "guidance": result.get("guidance", "")
        })

        return {
            "status": "success",
            "main_viewpoint": result.get("main_viewpoint", ""),
            "sub_goals": result.get("sub_goals", []),
            "guidance": result.get("guidance", ""),
            "updated_goals": meeting.knowledge_points
        }
    except Exception as e:
        print(f"[ERROR] quick-decompose: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


@app.post("/api/cluster-viewpoints")
async def cluster_viewpoints(
    meeting_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """聚类学生观点"""
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"status": "error", "message": "课堂不存在"}

        # 获取所有发言
        transcripts = db.query(Transcript).filter(
            Transcript.meeting_id == meeting_id
        ).order_by(Transcript.id).all()

        if len(transcripts) < 3:
            return {"status": "error", "message": "发言太少，无法聚类"}

        # 构建对话数据
        all_transcripts = [{
            "username": t.user.username,
            "content": t.content
        } for t in transcripts]

        # 调用LLM聚类观点
        result = llm.cluster_viewpoints(all_transcripts, meeting.topic)
        if research_runtime.research_algorithms_active:
            result = research_runtime.refine_viewpoint_clusters(all_transcripts, meeting.topic, result)

        # 创建投票记录
        import uuid
        vote_session_id = str(uuid.uuid4())[:8]
        vote_record = ViewpointVote(
            meeting_id=meeting_id,
            vote_session_id=vote_session_id,
            viewpoints=result.get("viewpoints", []),
            votes={str(vp["id"]): [] for vp in result.get("viewpoints", [])},
            status="active"
        )
        db.add(vote_record)
        db.commit()
        db.refresh(vote_record)

        # 广播投票开始
        vote_payload = {
            "type": "vote_start",
            "vote_id": vote_record.id,
            "vote_session_id": vote_session_id,
            "viewpoints": result.get("viewpoints", []),
            "summary": result.get("summary", ""),
            "suggested_next": result.get("suggested_next", ""),
            "votes": vote_record.votes,
            "online_members": manager.get_online_members(meeting_id)
        }
        if research_runtime.research_algorithms_active:
            vote_payload["research"] = result.get("research", {})
        await manager.broadcast_to_meeting(meeting_id, vote_payload)

        response_payload = {
            "status": "success",
            "vote_id": vote_record.id,
            "viewpoints": result.get("viewpoints", []),
            "summary": result.get("summary", ""),
            "suggested_next": result.get("suggested_next", "")
        }
        if research_runtime.research_algorithms_active:
            response_payload["research"] = result.get("research", {})
        return response_payload
    except Exception as e:
        print(f"[ERROR] 观点聚类失败: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/cast-vote")
async def cast_vote(
    vote_id: int = Form(...),
    viewpoint_id: int = Form(...),
    username: str = Form(...),
    meeting_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """学生投票"""
    try:
        vote_record = db.query(ViewpointVote).filter(ViewpointVote.id == vote_id).first()
        if not vote_record or vote_record.status != "active":
            return {"status": "error", "message": "投票不存在或已关闭"}

        # 获取投票数据
        votes = vote_record.votes or {}
        vp_key = str(viewpoint_id)

        # 移除旧投票
        for k in votes:
            if username in votes[k]:
                votes[k].remove(username)

        # 添加新投票
        if vp_key not in votes:
            votes[vp_key] = []
        votes[vp_key].append(username)

        vote_record.votes = votes
        db.commit()

        # 统计票数
        vote_counts = {k: len(v) for k, v in votes.items()}

        # 广播投票更新
        await manager.broadcast_to_meeting(meeting_id, {
            "type": "vote_update",
            "vote_id": vote_id,
            "votes": votes,
            "vote_counts": vote_counts,
            "voter": username,
            "voted_for": viewpoint_id
        })

        return {"status": "success", "votes": votes, "vote_counts": vote_counts}
    except Exception as e:
        print(f"[ERROR] 投票失败: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/close-vote")
async def close_vote(
    vote_id: int = Form(...),
    meeting_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """老师关闭投票"""
    try:
        from datetime import datetime
        vote_record = db.query(ViewpointVote).filter(ViewpointVote.id == vote_id).first()
        if not vote_record:
            return {"status": "error", "message": "投票不存在"}
        
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()

        # 统计票数
        votes = vote_record.votes or {}
        vote_counts = {k: len(v) for k, v in votes.items()}

        if not vote_counts:
            return {"status": "error", "message": "没有人投票"}
        
        winner_id = max(vote_counts, key=vote_counts.get)
        winner_viewpoint = None
        for vp in vote_record.viewpoints:
            if str(vp["id"]) == winner_id:
                winner_viewpoint = vp
                break
        
        if not winner_viewpoint:
            return {"status": "error", "message": "未找到获胜观点"}

        # 先关闭投票
        vote_record.status = "closed"
        vote_record.winner_viewpoint_id = int(winner_id)
        vote_record.closed_at = datetime.now()
        db.commit()

        # 立刻广播：关闭投票弹窗
        await manager.broadcast_to_meeting(meeting_id, {
            "type": "vote_result",
            "vote_id": vote_id,
            "winner_viewpoint": winner_viewpoint,
            "vote_counts": vote_counts,
            "sub_goals": [],
            "guidance": "",
            "updated_goals": None,
            "decomposing": True
        })

        # 同步执行 LLM 分解（像 quick_decompose 一样）
        try:
            print(f"[VOTE] 教师关闭投票，开始生成子目标, meeting_id={meeting_id}")
            sub_result = llm.generate_sub_goals(
                winner_viewpoint,
                meeting.topic,
                meeting.knowledge_points or []
            )
            print(f"[VOTE] LLM返回: {sub_result}")

            new_goals = list(meeting.knowledge_points or [])
            if sub_result.get("sub_goals"):
                for sg in sub_result["sub_goals"]:
                    new_goals.append({
                        "id": len(new_goals) + 1,
                        "desc": f"[深入探讨] {sg['desc']}",
                        "status": "pending",
                        "parent_viewpoint": winner_viewpoint.get("title", "")
                    })

            meeting.knowledge_points = new_goals
            db.commit()

            await manager.broadcast_to_meeting(meeting_id, {
                "type": "goals_updated",
                "updated_goals": new_goals,
                "main_viewpoint": winner_viewpoint.get("title", ""),
                "sub_goals": sub_result.get("sub_goals", []),
                "guidance": sub_result.get("guidance", "")
            })
            print(f"[VOTE] 教师关闭投票分解完成, 生成 {len(sub_result.get('sub_goals', []))} 个子目标")
        except Exception as ex:
            print(f"[ERROR] 教师关闭投票分解失败: {ex}")
            import traceback
            traceback.print_exc()
            await manager.broadcast_to_meeting(meeting_id, {
                "type": "goals_updated",
                "updated_goals": meeting.knowledge_points or [],
                "main_viewpoint": winner_viewpoint.get("title", "分解失败"),
                "sub_goals": [],
                "guidance": "任务分解失败，请稍后重试"
            })

        return {
            "status": "success",
            "winner_viewpoint": winner_viewpoint,
            "decomposing": True
        }
    except Exception as e:
        print(f"[ERROR] 关闭投票失败: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/confirm-vote")
async def confirm_vote(
    vote_id: int = Form(...),
    username: str = Form(...),
    meeting_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """成员确认观点选择完毕，当所有在线成员都确认后自动结束投票并重新生成任务分解"""
    try:
        vote_record = db.query(ViewpointVote).filter(ViewpointVote.id == vote_id).first()
        if not vote_record or vote_record.status != "active":
            return {"status": "error", "message": "投票已结束或不存在"}

        # 记录确认
        if vote_id not in manager.vote_confirmations:
            manager.vote_confirmations[vote_id] = set()
        manager.vote_confirmations[vote_id].add(username)

        confirmed = list(manager.vote_confirmations[vote_id])
        online = manager.get_online_members(meeting_id)

        # 广播确认状态
        await manager.broadcast_to_meeting(meeting_id, {
            "type": "vote_confirm",
            "confirmed_members": confirmed,
            "total_online": len(online),
            "confirmer": username
        })

        # 检查是否所有在线成员都已确认
        all_confirmed = all(m in manager.vote_confirmations[vote_id] for m in online)
        if all_confirmed and len(online) >= 1:
            print(f"[VOTE] 所有成员已确认, 开始处理投票结果")
            # 所有人确认完毕 → 立刻关闭投票弹窗，同步分解任务
            votes = vote_record.votes or {}
            vote_counts = {k: len(v) for k, v in votes.items()}
            print(f"[VOTE] votes={votes}, vote_counts={vote_counts}")

            winner_id = None
            winner_viewpoint = None
            if vote_counts:
                winner_id = max(vote_counts, key=vote_counts.get)
                for vp in (vote_record.viewpoints or []):
                    if str(vp.get("id")) == str(winner_id):
                        winner_viewpoint = vp
                        break
            print(f"[VOTE] winner_id={winner_id}, winner_viewpoint={winner_viewpoint}")

            # 先关闭投票记录
            vote_record.status = "closed"
            if winner_id is not None:
                vote_record.winner_viewpoint_id = int(winner_id)
            vote_record.closed_at = datetime.now()
            db.commit()
            manager.vote_confirmations.pop(vote_id, None)

            # 立刻广播：关闭投票弹窗
            await manager.broadcast_to_meeting(meeting_id, {
                "type": "vote_result",
                "winner_viewpoint": winner_viewpoint,
                "vote_counts": vote_counts,
                "decomposing": True
            })
            print(f"[VOTE] vote_result 已广播, 开始同步分解")

            # 同步执行 LLM 分解（像 quick_decompose 一样）
            try:
                meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
                winner_vp = winner_viewpoint or {"title": "无", "desc": ""}

                print(f"[VOTE] 开始生成子目标, meeting_id={meeting_id}")
                sub_result = llm.generate_sub_goals(
                    winner_vp,
                    meeting.topic,
                    meeting.knowledge_points or []
                )
                print(f"[VOTE] LLM返回: {sub_result}")

                new_goals = list(meeting.knowledge_points or [])
                for sg in sub_result.get("sub_goals", []):
                    new_goals.append({
                        "id": len(new_goals) + 1,
                        "desc": f"[深入探讨] {sg['desc']}",
                        "status": "pending",
                        "parent_viewpoint": winner_vp.get("title", "")
                    })

                meeting.knowledge_points = new_goals
                db.commit()

                # 广播分解结果到所有客户端
                await manager.broadcast_to_meeting(meeting_id, {
                    "type": "goals_updated",
                    "updated_goals": new_goals,
                    "main_viewpoint": winner_vp.get("title", ""),
                    "sub_goals": sub_result.get("sub_goals", []),
                    "guidance": sub_result.get("guidance", "")
                })
                print(f"[VOTE] 分解完成, 生成 {len(sub_result.get('sub_goals', []))} 个子目标")
            except Exception as ex:
                print(f"[ERROR] 分解失败: {ex}")
                import traceback
                traceback.print_exc()
                # 通知客户端分解失败，关闭加载状态
                await manager.broadcast_to_meeting(meeting_id, {
                    "type": "goals_updated",
                    "updated_goals": meeting.knowledge_points or [],
                    "main_viewpoint": winner_vp.get("title", "分解失败，请重试") if winner_viewpoint else "分解失败",
                    "sub_goals": [],
                    "guidance": "任务分解失败，请稍后重试"
                })

        return {"status": "success", "confirmed": confirmed, "total_online": len(online)}
    except Exception as e:
        print(f"[ERROR] confirm-vote: {e}")
        return {"status": "error", "message": str(e)}
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


@app.get("/api/class-history/{user_id}")
async def get_class_history(user_id: int, db: Session = Depends(get_db)):
    """获取用户的课堂历史"""
    try:
        from datetime import datetime

        # 查询参与的课堂
        user_meetings = db.query(Meeting).join(Transcript).filter(
            Transcript.user_id == user_id
        ).distinct().all()

        # 查询创建的课堂
        created_meetings = db.query(Meeting).filter(
            Meeting.teacher_id == user_id
        ).all()

        all_meetings = list(set(user_meetings + created_meetings))

        history = []
        for m in all_meetings:
            # 统计参与人数
            participant_count = db.query(Transcript.user_id).filter(
                Transcript.meeting_id == m.id
            ).distinct().count()

            # 获取报告
            first_transcript = db.query(Transcript).filter(
                Transcript.meeting_id == m.id
            ).order_by(Transcript.created_at).first()
            
            last_transcript = db.query(Transcript).filter(
                Transcript.meeting_id == m.id
            ).order_by(Transcript.created_at.desc()).first()
            
            start_time = first_transcript.created_at if first_transcript else m.created_at
            end_time = last_transcript.created_at if last_transcript else m.created_at

            # 查询该用户在此会议的发言数
            user_speech_count = db.query(Transcript).filter(
                Transcript.meeting_id == m.id,
                Transcript.user_id == user_id
            ).count()

            # 查询是否有报告
            has_report = db.query(LearningReport).filter(
                LearningReport.meeting_id == m.id,
                LearningReport.user_id == user_id
            ).first() is not None

            history.append({
                "meeting_id": m.id,
                "class_code": m.class_code,
                "topic": m.topic,
                "status": m.status,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "duration_minutes": int((end_time - start_time).total_seconds() / 60),
                "participant_count": participant_count,
                "speech_count": user_speech_count,
                "has_report": has_report,
                "created_at": m.created_at.isoformat()
            })

        # 按时间倒序排列
        history.sort(key=lambda x: x["created_at"], reverse=True)

        return {"status": "success", "history": history}
    except Exception as e:
        print(f"[ERROR] 获取历史失败: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/student-home-stats/{user_id}")
async def get_student_home_stats(user_id: int, db: Session = Depends(get_db)):
    """涓虹櫥褰曞悗棣栭〉鎻愪緵杞婚噺瀛︿範姒傝鏁版嵁"""
    try:
        meeting_ids = [
            int(meeting_id)
            for (meeting_id,) in db.query(Transcript.meeting_id).filter(
                Transcript.user_id == user_id
            ).distinct().all()
        ]
        if not meeting_ids:
            return {
                "status": "success",
                "stats": {
                    "activeClasses": 0,
                    "completedClasses": 0,
                    "studyHours": "0.0",
                }
            }

        meetings = db.query(Meeting).filter(Meeting.id.in_(meeting_ids)).all()
        window_map = _build_meeting_window_map(db, meeting_ids)

        active_classes = 0
        completed_classes = 0
        total_minutes = 0
        for meeting in meetings:
            if meeting.status == "active":
                active_classes += 1
            else:
                completed_classes += 1

            window = window_map.get(int(meeting.id), {})
            start_time = window.get("first_at") or meeting.created_at
            end_time = window.get("last_at") or meeting.created_at
            total_minutes += max(0, int((end_time - start_time).total_seconds() / 60))

        return {
            "status": "success",
            "stats": {
                "activeClasses": active_classes,
                "completedClasses": completed_classes,
                "studyHours": f"{(total_minutes / 60):.1f}",
            }
        }
    except Exception as e:
        print(f"[ERROR] 鑾峰彇棣栭〉缁熻澶辫触: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/active-groups/{teacher_id}")
async def get_active_groups(teacher_id: int, db: Session = Depends(get_db)):
    """获取老师的活跃课堂"""
    try:
        # 查询活跃课堂
        meetings = db.query(Meeting).filter(
            Meeting.teacher_id == teacher_id,
            Meeting.status == "active"
        ).all()

        groups = []
        for m in meetings:
            # 统计发言数
            speech_count = db.query(Transcript).join(User, User.id == Transcript.user_id).filter(
                Transcript.meeting_id == m.id,
                User.role != "teacher"
            ).count()

            # 参与成员数（排除老师）
            member_count = db.query(Transcript.user_id).join(User, User.id == Transcript.user_id).filter(
                Transcript.meeting_id == m.id,
                User.role != "teacher"
            ).distinct().count()

            # 计算活跃度（避免轻易封顶 100）
            avg_speech = speech_count / max(member_count, 1)
            base = min(60.0, avg_speech * 12.0)          # 0~60：人均发言贡献
            volume = min(30.0, speech_count * 0.8)       # 0~30：总体发言量
            breadth = min(10.0, member_count * 1.0)      # 0~10：参与广度
            score = int(min(100.0, base + volume + breadth))

            # 状态标签
            if speech_count < 5:
                status_tag = "冷清"
            elif avg_speech < 2:
                status_tag = "一般"
            else:
                status_tag = "活跃"

            groups.append({
                "meeting_id": m.id,
                "class_code": m.class_code,
                "topic": m.topic,
                "member_count": member_count,
                "speech_count": speech_count,
                "score": score,
                "status_tag": status_tag
            })

        # 按分数排序
        groups.sort(key=lambda x: x['score'], reverse=True)

        return {"status": "success", "groups": groups}
    except Exception as e:
        print(f"[ERROR] 获取活跃课堂失败: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/realtime-stats/{meeting_id}")
async def get_realtime_stats(meeting_id: int, db: Session = Depends(get_db)):
    """获取实时统计数据"""
    try:
        import time
        start_time = time.time()
        print(f"[TIME] [realtime-stats] 开始查询 meeting_id={meeting_id}")

        # 使用joinedload优化查询
        from sqlalchemy.orm import joinedload

        # [OK] 查询转录
        transcripts = db.query(Transcript).options(
            joinedload(Transcript.user)
        ).filter(
            Transcript.meeting_id == meeting_id
        ).order_by(Transcript.timestamp.desc()).all()

        # 反转顺序
        transcripts.reverse()

        print(f"  [OK] 查询到 {len(transcripts)} 条发言: {time.time() - start_time:.2f}秒")

        # [OK] 查询情绪
        emotions = db.query(EmotionLog).options(
            joinedload(EmotionLog.user)
        ).filter(
            EmotionLog.meeting_id == meeting_id
        ).order_by(EmotionLog.created_at.desc()).all()

        emotions.reverse()

        print(f"  [OK] 查询到 {len(emotions)} 条情绪: {time.time() - start_time:.2f}秒")

        # 1. 发言统计
        speech_stats = {}
        user_transcripts = {}  # 保存每个用户的发言
        for t in transcripts:
            username = t.user.username
            speech_stats[username] = speech_stats.get(username, 0) + 1
            if username not in user_transcripts:
                user_transcripts[username] = []
            user_transcripts[username].append(t.content)

        pie_data = [{'name': k, 'value': v} for k, v in speech_stats.items()]

        # 2. 互动网络
        users = list(speech_stats.keys())
        interaction_matrix = {u: {u2: 0 for u2 in users} for u in users}

        # 统计互动
        for i in range(1, len(transcripts)):
            prev_user = transcripts[i-1].user.username
            curr_user = transcripts[i].user.username
            if prev_user != curr_user:
                interaction_matrix[prev_user][curr_user] += 1
                interaction_matrix[curr_user][prev_user] += 1

        # 转换为ECharts格式
        nodes = [{'name': u, 'value': speech_stats[u]} for u in users]
        edges = []
        for u1 in users:
            for u2 in users:
                if u1 < u2 and interaction_matrix[u1][u2] > 0:
                    edges.append({
                        'source': u1,
                        'target': u2,
                        'value': interaction_matrix[u1][u2]
                    })

        # 3. 情绪时间线
        emotion_timeline = {}
        user_emotions = {}  # 保存每个用户的情绪
        for e in emotions:
            username = e.user.username
            if username not in emotion_timeline:
                emotion_timeline[username] = []
                user_emotions[username] = []
            
            emotion_type = normalize_emotion_label(e.emotion_type)
            emotion_value = emotion_value_for_label(emotion_type)
            
            emotion_timeline[username].append({
                'time': e.created_at.isoformat(),
                'value': emotion_value,
                'emotion': emotion_type
            })
            user_emotions[username].append(emotion_value)
        
        # 4. 成员综合评分
        member_scores = []
        total_speeches = sum(speech_stats.values()) if speech_stats else 1

        # 收集每个用户的quality_score
        user_quality_scores = {}
        for t in transcripts:
            username = t.user.username
            if username not in user_quality_scores:
                user_quality_scores[username] = []
            if hasattr(t, 'quality_score') and t.quality_score:
                user_quality_scores[username].append(t.quality_score)

        for username in users:
            speech_count = speech_stats.get(username, 0)

            # LLM评分50分满分
            quality_scores = user_quality_scores.get(username, [])
            avg_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 50
            llm_score = avg_quality * 0.5  # 0-50分

            # 参与度25分满分
            speech_ratio = speech_count / total_speeches
            if 0.15 <= speech_ratio <= 0.35:
                participation_score = 25
            elif speech_ratio < 0.15:
                participation_score = max(10, 25 * (speech_ratio / 0.15))
            else:
                participation_score = max(15, 25 - (speech_ratio - 0.35) * 50)

            # 互动性15分满分
            interaction_count = sum(interaction_matrix.get(username, {}).values())
            interaction_score = min(15, interaction_count * 2.5)

            # 情绪状态10分满分- 积极情绪加分
            avg_emotion = sum(user_emotions.get(username, [50])) / len(user_emotions.get(username, [50]))
            emotion_score = avg_emotion * 0.1  # 0-10分

            total_score = int(llm_score + participation_score + interaction_score + emotion_score)
            total_score = max(0, min(100, total_score))  # 限制在0-100

            # 获取最新反馈
            latest_feedback = ""
            for t in reversed(transcripts):
                if t.user.username == username and hasattr(t, 'quality_feedback') and t.quality_feedback:
                    latest_feedback = t.quality_feedback
                    break
            
            member_scores.append({
                'name': username,
                'score': total_score,
                'speech_count': speech_count,
                'interaction_count': interaction_count,
                'avg_emotion': int(avg_emotion),
                'avg_quality': int(avg_quality),
                'latest_feedback': latest_feedback
            })
        
        # ??
        member_scores.sort(key=lambda x: x['score'], reverse=True)
        
        print(f"  [OK] ??: {time.time() - start_time:.2f}??")
        
        return {
            'status': 'success',
            'pie_data': pie_data,
            'interaction': {'nodes': nodes, 'edges': edges},
            'emotion_timeline': emotion_timeline,
            'member_scores': member_scores
        }
    except Exception as e:
        print(f'[ERROR] ??: {e}')
        import traceback
        traceback.print_exc()
        return {'status': 'error', 'message': str(e)}


# 新增接口: 情绪详情API
@app.get("/api/emotion-details/{meeting_id}")
async def get_emotion_details(
    meeting_id: int,
    username: str = None,
    minutes: int = 15,
    db: Session = Depends(get_db)
):
    """获取情绪详细数据"""
    try:
        import time
        start_time = time.time()
        print(f"[TIME] [emotion-details] 开始查询 meeting_id={meeting_id}")
        # minutes 支持:
        # - 5/15/30: 最近 N 分钟
        # - 0: 整节课（不过滤时间）
        allowed_windows = {0, 5, 15, 30}
        if minutes not in allowed_windows:
            minutes = 15
        cutoff_time = datetime.now() - timedelta(minutes=minutes) if minutes > 0 else None

        # 使用joinedload避免N+1查询问题
        from sqlalchemy.orm import joinedload

        # [OK] 查询情绪
        emotion_query = db.query(EmotionLog).options(
            joinedload(EmotionLog.user)
        ).filter(
            EmotionLog.meeting_id == meeting_id
        )
        if cutoff_time is not None:
            emotion_query = emotion_query.filter(EmotionLog.created_at >= cutoff_time)
        emotions = emotion_query.order_by(EmotionLog.created_at.desc()).all()

        print(f"  [OK] 查询到 {len(emotions)} 条情绪: {time.time() - start_time:.2f}秒")

        # [OK] 查询转录
        transcript_query = db.query(Transcript).options(
            joinedload(Transcript.user)
        ).filter(
            Transcript.meeting_id == meeting_id
        )
        if cutoff_time is not None:
            transcript_query = transcript_query.filter(Transcript.timestamp >= cutoff_time)
        transcripts = transcript_query.order_by(Transcript.timestamp.desc()).all()

        print(f"  [OK] 查询到 {len(transcripts)} 条发言: {time.time() - start_time:.2f}秒")

        # 反转顺序
        emotions.reverse()
        transcripts.reverse()

        # 1. 个人情绪时间线 (智能采样：动态间隔 + 大幅波动时额外记录)
        individual_emotions = {}
        last_emotion_by_user = {}      # {username: last_emotion_value}
        last_point_time_by_user = {}   # {username: last_point_timestamp}

        # 动态采样间隔：根据课堂时长自适应
        # 短课堂（<30分钟）：2分钟间隔
        # 中等课堂（30-60分钟）：5分钟间隔
        # 长课堂（>60分钟）：10分钟间隔
        if emotions:
            course_duration_minutes = (emotions[-1].created_at - emotions[0].created_at).total_seconds() / 60
            if course_duration_minutes < 30:
                INTERVAL_SECONDS = 2 * 60   # 2分钟
            elif course_duration_minutes < 60:
                INTERVAL_SECONDS = 5 * 60   # 5分钟
            else:
                INTERVAL_SECONDS = 10 * 60  # 10分钟
        else:
            INTERVAL_SECONDS = 2 * 60       # 默认2分钟

        BIG_SHIFT_THRESHOLD = 15       # 情绪值变化超过15视为大幅波动

        for e in emotions:
            uname = e.user.username
            if uname not in individual_emotions:
                individual_emotions[uname] = []

            emotion_type = normalize_emotion_label(e.emotion_type)
            emotion_value = emotion_value_for_label(emotion_type)

            current_ts = e.created_at.timestamp()
            should_add = False

            if uname not in last_emotion_by_user:
                # 第一个点，必须加
                should_add = True
            else:
                last_val = last_emotion_by_user[uname]
                last_ts = last_point_time_by_user[uname]
                time_gap = current_ts - last_ts

                # 大幅情绪波动（即使在15分钟内也要加）
                if abs(emotion_value - last_val) >= BIG_SHIFT_THRESHOLD:
                    should_add = True
                # 超过15分钟间隔，保底加一个点
                elif time_gap >= INTERVAL_SECONDS:
                    should_add = True

            if should_add:
                last_emotion_by_user[uname] = emotion_value
                last_point_time_by_user[uname] = current_ts
                individual_emotions[uname].append({
                    'id': e.id,
                    'time': e.created_at.isoformat(),
                    'timestamp': int(e.created_at.timestamp() * 1000),
                    'emotion_type': emotion_type,
                    'emotion_value': emotion_value,
                    'intensity': e.intensity,
                    'snapshot_path': e.snapshot_path
                })

        # 确保每个用户的最后一个情绪记录也被包含（折线不会断在中间）
        for e in reversed(emotions):
            uname = e.user.username
            if uname in individual_emotions and individual_emotions[uname]:
                last_point = individual_emotions[uname][-1]
                if last_point['id'] != e.id:
                    emotion_type = normalize_emotion_label(e.emotion_type)
                    emotion_value = emotion_value_for_label(emotion_type)
                    individual_emotions[uname].append({
                        'id': e.id,
                        'time': e.created_at.isoformat(),
                        'timestamp': int(e.created_at.timestamp() * 1000),
                        'emotion_type': emotion_type,
                        'emotion_value': emotion_value,
                        'intensity': e.intensity,
                        'snapshot_path': e.snapshot_path
                    })
                # 只处理每个用户一次
                last_emotion_by_user.pop(uname, None)
            if not last_emotion_by_user:
                break

        # 2. 全班情绪趋势
        all_emotions_timeline = []
        time_buckets = {}  # 按分钟聚合

        for e in emotions:
            time_key = e.created_at.strftime('%Y-%m-%d %H:%M')  # 按分钟分组
            if time_key not in time_buckets:
                time_buckets[time_key] = []

            emotion_type = normalize_emotion_label(e.emotion_type)
            emotion_value = emotion_value_for_label(emotion_type)
            
            time_buckets[time_key].append(emotion_value)
        
        for time_key in sorted(time_buckets.keys()):
            values = time_buckets[time_key]
            avg_value = sum(values) / len(values) if values else 50
            all_emotions_timeline.append({
                'time': time_key,
                'value': int(avg_value),
                'count': len(values)
            })
        
        # 3. 视频片段列表
        video_segments = []
        for t in transcripts:
            if t.audio_file_path:
                # 推测视频路径
                video_path = t.audio_file_path.replace('audio_chunks', 'video_chunks').replace('.wav', '.webm')

                video_segments.append({
                    'id': t.id,
                    'username': t.user.username,
                    'text': t.content,
                    'emotion': t.emotion_tag or 'neutral',
                    'timestamp': int(t.timestamp.timestamp() * 1000),
                    'time': t.timestamp.isoformat(),
                    'video_path': video_path,
                    'audio_path': t.audio_file_path
                })

        print(f"  [OK] 处理完成: {time.time() - start_time:.2f}秒")

        # 如果指定了username，个体情绪只返回该用户自己的数据（隐私保护）
        # 但群体情绪图表需要所有人的数据，所以返回两份
        filtered_individual = individual_emotions
        current_user_key = None
        if username:
            filtered_individual = {}
            candidate_keys = {str(username)}
            resolved_user = resolve_user_by_identifier(db, username)
            if resolved_user:
                if getattr(resolved_user, "username", None):
                    candidate_keys.add(str(resolved_user.username))
                if getattr(resolved_user, "student_id", None):
                    candidate_keys.add(str(resolved_user.student_id))

            for key in candidate_keys:
                if key in individual_emotions:
                    filtered_individual[key] = individual_emotions[key]
                    current_user_key = key
                    break

            # 兼容旧数据：如果查询参数没对上，但该课堂只有一个人的情绪曲线，
            # 不返回空图，直接给学生端展示这条曲线。
            if not filtered_individual and len(individual_emotions) == 1:
                current_user_key = next(iter(individual_emotions.keys()))
                filtered_individual[current_user_key] = individual_emotions[current_user_key]

        return {
            'status': 'success',
            'individual_emotions': filtered_individual,  # 个体图表用（可能被过滤）
            'all_individual_emotions': individual_emotions,  # 群体图表用（完整数据）
            'group_emotion_timeline': all_emotions_timeline,
            'video_segments': video_segments,
            'current_user_key': current_user_key
        }
    except Exception as e:
        print(f'[ERROR] ??a??: {e}')
        import traceback
        traceback.print_exc()
        return {'status': 'error', 'message': str(e)}


# 新增接口: 获取快照
@app.get("/api/snapshot/{meeting_id}")
async def get_snapshot(meeting_id: int, username: str, timestamp: int, db: Session = Depends(get_db)):
    """获取指定时间点的快照"""
    try:
        # 转换为 datetime
        from datetime import datetime
        target_time = datetime.fromtimestamp(timestamp / 1000)

        # 查询用户
        user = resolve_user_by_identifier(db, username)
        if not user:
            return {'status': 'error', 'message': '用户不存在'}

        # 查询前后5秒范围
        from sqlalchemy import and_
        from datetime import timedelta

        time_start = target_time - timedelta(seconds=5)
        time_end = target_time + timedelta(seconds=5)

        candidates = db.query(EmotionLog).filter(
            and_(
                EmotionLog.meeting_id == meeting_id,
                EmotionLog.user_id == user.id,
                EmotionLog.created_at >= time_start,
                EmotionLog.created_at <= time_end,
                EmotionLog.snapshot_path.isnot(None)
            )
        ).all()
        emotion = min(
            candidates,
            key=lambda e: abs((e.created_at - target_time).total_seconds())
        ) if candidates else None

        if emotion and emotion.snapshot_path:
            return {
                'status': 'success',
                'snapshot_path': emotion.snapshot_path,
                'emotion_type': emotion.emotion_type,
                'timestamp': int(emotion.created_at.timestamp() * 1000)
            }
        else:
            return {'status': 'error', 'message': '未找到快照'}
    except Exception as e:
        print(f'[ERROR] 获取快照失败: {e}')
        import traceback
        traceback.print_exc()
        return {'status': 'error', 'message': str(e)}


# 新增接口: 获取视频上下文
@app.get("/api/get-video-context")
async def get_video_context(
    meeting_id: int,
    timestamp: float,  # 时间戳
    user_id: Optional[int] = None,  # 用户ID参数（兼容旧版）
    username: Optional[str] = None,  # 新增：用户名/学号参数
    db: Session = Depends(get_db)
):
    """
    根据时间戳获取对应的视频片段
    返回值: {video_url, jump_to_time}
    """
    try:
        print(f"[QUERY] 查询视频上下文: meeting_id={meeting_id}, user_id={user_id}, username={username}, timestamp={timestamp}")
        from datetime import datetime, timedelta

        # 转换时间戳
        if timestamp > 10000000000:  # 毫秒级
            target_time = datetime.fromtimestamp(timestamp / 1000)
        else:  # 秒级
            target_time = datetime.fromtimestamp(timestamp)

        print(f"转换后 目标时间: {target_time}")

        # 查询前后±10秒范围

        time_start = target_time - timedelta(seconds=10)
        time_end = target_time + timedelta(seconds=10)

        print(f"[ZOOM2] 时间范围: {time_start} ~ {time_end}")

        # 解析用户ID（优先显式 user_id；否则通过 username/student_id 反查）
        resolved_user_id = user_id
        if not resolved_user_id and username:
            u = resolve_user_by_identifier(db, username)
            resolved_user_id = u.id if u else None

        if not resolved_user_id:
            return {'status': 'error', 'message': '缺少有效用户标识'}

        # 查询指定meeting_id和user_id
        candidates = db.query(EmotionLog).filter(
            EmotionLog.meeting_id == meeting_id,
            EmotionLog.user_id == resolved_user_id,
            EmotionLog.created_at >= time_start,
            EmotionLog.created_at <= time_end,
            EmotionLog.video_url.isnot(None)
        ).all()
        emotion = min(
            candidates,
            key=lambda e: abs((e.created_at - target_time).total_seconds())
        ) if candidates else None

        if not emotion:
            print(f"[ERROR] 未找到视频记录")
            # 返回错误
            return {'status': 'error', 'message': '未找到对应的视频片段'}

        print(f"[OK] 找到记录: ID={emotion.id}, video_url={emotion.video_url[:80]}...")

        # 检查video_url
        if not emotion.video_url:
            return {'status': 'error', 'message': '视频URL为空'}

        video_url = str(emotion.video_url or "").replace("\\", "/")
        if video_url and (not video_url.startswith("http")) and (not video_url.startswith("/")):
            video_url = "/" + video_url

        # OSS URL检查
        if video_url.startswith('http'):
            print(f'[OK] 返回OSS链接: {video_url[:80]}...')
        else:
            print(f'[WARN] 本地URL路径: {video_url}')

        jump_to_time = emotion.video_start_time if emotion.video_start_time else 0

        return {
            'status': 'success',
            'video_url': video_url,
            'jump_to_time': jump_to_time,
            'emotion_type': emotion.emotion_type,
            'timestamp': int(emotion.created_at.timestamp() * 1000)
        }

    except Exception as e:
        print(f'[ERROR] 查询失败: {e}')
        import traceback
        traceback.print_exc()
        return {'status': 'error', 'message': f'查询失败: {str(e)}'}


@app.post("/api/generate-pdf-report")
async def generate_pdf_report(
    meeting_id: int = Form(...),
    user_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """生成学习报告PDF文件"""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib import colors
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import io

        # 注册中文字体
        chinese_font = 'Helvetica'
        font_paths = [
            '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',      # Ubuntu wqy-zenhei
            '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',     # Ubuntu wqy-microhei
            '/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc',         # CentOS
            '/usr/share/fonts/chinese/simhei.ttf',                  # 手动安装
            'C:/Windows/Fonts/simhei.ttf',                          # Windows
            'C:/Windows/Fonts/msyh.ttc',                            # Windows 微软雅黑
        ]
        for fp in font_paths:
            try:
                if os.path.exists(fp):
                    if fp.endswith('.ttc'):
                        pdfmetrics.registerFont(TTFont('ChineseFont', fp, subfontIndex=0))
                    else:
                        pdfmetrics.registerFont(TTFont('ChineseFont', fp))
                    chinese_font = 'ChineseFont'
                    print(f"[OK] PDF中文字体已加载: {fp}")
                    break
            except Exception as fe:
                print(f"[WARN] 字体 {fp} 加载失败: {fe}")
                continue

        # 查询最新的报告
        report = db.query(LearningReport).filter(
            LearningReport.meeting_id == meeting_id,
            LearningReport.user_id == user_id
        ).order_by(LearningReport.created_at.desc()).first()

        if not report:
            return {"status": "error", "message": "报告不存在"}

        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        user = db.query(User).filter(User.id == user_id).first()

        # 创建PDF文件
        pdf_dir = "storage/reports"
        os.makedirs(pdf_dir, exist_ok=True)
        pdf_filename = f"report_{meeting_id}_{user_id}_{int(time.time())}.pdf"
        pdf_path = os.path.join(pdf_dir, pdf_filename)

        doc = SimpleDocTemplate(pdf_path, pagesize=A4)
        story = []
        styles = getSampleStyleSheet()

        # 定义样式
        title_style = ParagraphStyle(
            'ChineseTitle',
            parent=styles['Title'],
            fontName=chinese_font,
            fontSize=18
        )
        heading_style = ParagraphStyle(
            'ChineseHeading',
            parent=styles['Heading2'],
            fontName=chinese_font,
            fontSize=14
        )
        body_style = ParagraphStyle(
            'ChineseBody',
            parent=styles['Normal'],
            fontName=chinese_font,
            fontSize=11,
            leading=18
        )

        data = report.report_data

        # 标题
        story.append(Paragraph(f"学习报告 - {data.get('meeting_topic', '')}", title_style))
        story.append(Spacer(1, 20))

        # 基本信息
        story.append(Paragraph("基本信息", heading_style))
        story.append(Paragraph(f"学生姓名：{data.get('student_name', '')}", body_style))
        story.append(Paragraph(f"发言次数：{data.get('speech_count', 0)}", body_style))
        story.append(Paragraph(f"平均相关度：{data.get('avg_relevance', 0)}", body_style))
        story.append(Spacer(1, 15))

        # 优势分析
        story.append(Paragraph("课程总结", heading_style))
        story.append(Paragraph(data.get('course_summary', '暂无总结'), body_style))
        story.append(Spacer(1, 15))

        # 优劣势分析
        story.append(Paragraph("优劣势分析", heading_style))
        strengths = data.get('strengths', [])
        if strengths:
            story.append(Paragraph("优势：" + "；".join(strengths), body_style))
        weaknesses = data.get('weaknesses', [])
        if weaknesses:
            story.append(Paragraph("待改进：" + "；".join(weaknesses), body_style))
        story.append(Spacer(1, 15))

        # 改进建议
        story.append(Paragraph("改进建议", heading_style))
        story.append(Paragraph(data.get('improvement_suggestions', '继续保持'), body_style))

        doc.build(story)

        return {
            "status": "success",
            "pdf_url": f"/storage/reports/{pdf_filename}",
            "filename": pdf_filename
        }
    except ImportError:
        return {"status": "error", "message": "缺少reportlab库: pip install reportlab"}
    except Exception as e:
        print(f"[ERROR] PDF生成失败: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}


@app.get("/api/download-exercises/{report_id}")
async def download_exercises(report_id: int, db: Session = Depends(get_db)):
    """下载练习题"""
    try:
        # 查询练习题
        exercises = db.query(Exercise).filter(Exercise.report_id == report_id).all()

        if not exercises:
            return {"status": "error", "message": "没有练习题"}

        report = db.query(LearningReport).filter(LearningReport.id == report_id).first()
        meeting = db.query(Meeting).filter(Meeting.id == report.meeting_id).first()

        # 生成JSON格式
        exercise_dir = "storage/exercises"
        os.makedirs(exercise_dir, exist_ok=True)
        filename = f"exercises_{report_id}_{int(time.time())}.txt"
        filepath = os.path.join(exercise_dir, filename)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(f"练习题集 - {meeting.topic if meeting else '未知课堂'}\n")
            f.write("=" * 50 + "\n\n")

            for i, ex in enumerate(exercises, 1):
                f.write(f"题目 {i}: {ex.question}\n")
                f.write(f"类型: {ex.question_type}\n")
                f.write(f"难度: {ex.difficulty}\n")

                if ex.options:
                    f.write("选项:\n")
                    # 处理不同格式
                    if isinstance(ex.options, dict):
                        for opt_key, opt_val in ex.options.items():
                            opt_text = str(opt_val or '').strip()
                            # 避免出现类似 “A. A. xxx” 的重复前缀
                            opt_text = re.sub(r'^\s*[A-Da-d]\s*[\.、:：]\s*', '', opt_text)
                            f.write(f"  {opt_key}. {opt_text}\n")
                    elif isinstance(ex.options, list):
                        for idx, opt in enumerate(ex.options):
                            opt_key = chr(65 + idx)  # A, B, C, D...
                            opt_text = str(opt or '').strip()
                            # 避免出现类似 “A. A. xxx” 的重复前缀
                            opt_text = re.sub(r'^\s*[A-Da-d]\s*[\.、:：]\s*', '', opt_text)
                            f.write(f"  {opt_key}. {opt_text}\n")
                    else:
                        f.write(f"  {ex.options}\n")

                f.write(f"知识点: {ex.knowledge_tag or '综合'}\n")
                f.write(f"答案: {ex.answer}\n")
                f.write("-" * 40 + "\n\n")
        
        return FileResponse(
            path=filepath,
            filename=f"??_{meeting.topic if meeting else 'exercises'}.txt",
            media_type="text/plain"
        )
    except Exception as e:
        print(f"[ERROR] ??: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/quiz-error-analysis")
async def quiz_error_analysis(
    wrong_questions: str = Form(...),
    topic: str = Form(default=""),
    db: Session = Depends(get_db)
):
    """AI分析错题，给出学习建议"""
    try:
        import json as _json
        questions = _json.loads(wrong_questions)
        if not questions:
            return {"status": "success", "analysis": "没有错题，表现很棒！"}

        wrong_text = "\n".join([
            f"- 题目：{q.get('question', '未知')}\n  正确答案：{q.get('correctAnswer', '未知')}"
            for q in questions
        ])

        prompt = f"""课程主题：{topic}

以下是学生答错的题目：
{wrong_text}

请用Markdown格式分析这些错题，给出：
1. **易错知识点归纳**：列出学生可能薄弱的知识点
2. **错因分析**：分析常见的错误原因
3. **改进建议**：给出具体可操作的学习建议
4. **推荐复习方向**：指出应该重点复习的内容

请简洁明了，使用列表和加粗等格式突出重点，总字数控制在200-400字。"""

        try:
            response = llm.client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": "你是一位经验丰富的教育分析师，善于从错题中发现学生的薄弱点并给出针对性建议。使用Markdown格式回复。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.4,
                max_tokens=800
            )
            analysis = response.choices[0].message.content.strip()
        except Exception as e:
            print(f"[ERROR] AI错题分析失败: {e}")
            analysis = f"**错题数量**：{len(questions)}道\n\n**涉及知识点**：{topic}\n\n建议重点复习相关知识点，多做类似练习题巩固理解。"

        return {"status": "success", "analysis": analysis}
    except Exception as e:
        print(f"[ERROR] quiz-error-analysis: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/grade-short-answer")
async def grade_short_answer(
    question: str = Form(...),
    correct_answer: str = Form(...),
    student_answer: str = Form(...),
    question_type: str = Form("简答题")
):
    """大模型评判简答/讨论题"""
    try:
        prompt = f"""你是一位严格但公正的阅卷老师，请评判学生的回答。

题目：{question}
参考答案：{correct_answer}
学生回答：{student_answer}
题目类型：{question_type}

评判标准：
- 如果是讨论题/开放题：答案不需要完全一致，但必须言之有理、观点明确、有逻辑性。空洞无意义的回答应判错。
- 如果是简答题：核心要点必须涵盖，表述可以不同但含义要正确。
- 只回答一两个字、敷衍了事的回答应判错。

请严格按以下JSON格式回复：
{{"is_correct": true或false, "feedback": "20-50字的评语，指出优点或不足"}}"""

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, llm._call_json, prompt)
        is_correct = bool(result.get("is_correct", False))
        feedback = result.get("feedback", "")
        return {"status": "success", "is_correct": is_correct, "feedback": feedback}
    except Exception as e:
        print(f"[ERROR] grade-short-answer: {e}")
        return {"status": "success", "is_correct": True, "feedback": "评分服务暂不可用，默认通过"}


@app.post("/api/submit-answer")
async def submit_answer(
    exercise_id: int = Form(...),
    user_id: int = Form(...),
    answer_content: str = Form(...),
    is_correct: int = Form(...),
    db: Session = Depends(get_db)
):
    """保存学生答题记录"""
    try:
        # 检查是否已有该题的回答记录
        existing = db.query(StudentAnswer).filter(
            StudentAnswer.exercise_id == exercise_id,
            StudentAnswer.user_id == user_id
        ).first()

        if existing:
            existing.answer_content = answer_content
            existing.is_correct = is_correct
            existing.submitted_at = datetime.now()
        else:
            sa = StudentAnswer(
                exercise_id=exercise_id,
                user_id=user_id,
                answer_content=answer_content,
                is_correct=is_correct
            )
            db.add(sa)
        db.commit()
        return {"status": "success"}
    except Exception as e:
        print(f"[ERROR] submit-answer: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/student-quiz-history/{user_id}")
async def get_student_quiz_history(user_id: int, db: Session = Depends(get_db)):
    """获取学生的答题历史统计"""
    try:
        answers = db.query(StudentAnswer).filter(StudentAnswer.user_id == user_id).all()
        total = len(answers)
        correct = sum(1 for a in answers if a.is_correct == 1)
        wrong = total - correct

        # 获取错题详情
        wrong_answers = [a for a in answers if a.is_correct == 0]
        wrong_details = []
        for wa in wrong_answers:
            ex = db.query(Exercise).filter(Exercise.id == wa.exercise_id).first()
            if ex:
                wrong_details.append({
                    "exercise_id": ex.id,
                    "question": ex.question,
                    "type": ex.question_type,
                    "correct_answer": ex.answer,
                    "student_answer": wa.answer_content,
                    "knowledge_tag": ex.knowledge_tag,
                    "submitted_at": wa.submitted_at.isoformat() if wa.submitted_at else None
                })

        return {
            "status": "success",
            "total": total,
            "correct": correct,
            "wrong": wrong,
            "accuracy": round(correct / total * 100, 1) if total > 0 else 0,
            "wrong_details": wrong_details
        }
    except Exception as e:
        print(f"[ERROR] student-quiz-history: {e}")
        return {"status": "error", "message": str(e)}
async def upload_report_template(
    template_file: UploadFile = File(...),
    teacher_id: int = Form(...),
    db: Session = Depends(get_db)
):
    """??"""
    try:
        from database import ReportTemplate
        
        template_dir = "storage/templates"
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


@app.get("/api/teacher-templates/{teacher_id}")
async def get_teacher_templates(teacher_id: int, db: Session = Depends(get_db)):
    """??"""
    try:
        from database import ReportTemplate
        
        templates = db.query(ReportTemplate).filter(
            ReportTemplate.teacher_id == teacher_id
        ).order_by(ReportTemplate.created_at.desc()).all()
        
        result = []
        for t in templates:
            result.append({
                "id": t.id,
                "filename": t.filename,
                "filepath": t.filepath,
                "is_default": t.is_default,
                "created_at": t.created_at.isoformat()
            })
        
        return {"status": "success", "templates": result}
    except Exception as e:
        print(f"[ERROR] ??: {e}")
        return {"status": "error", "message": str(e)}


@app.delete("/api/delete-template/{template_id}")
async def delete_template(template_id: int, db: Session = Depends(get_db)):
    """??"""
    try:
        from database import ReportTemplate
        
        template = db.query(ReportTemplate).filter(ReportTemplate.id == template_id).first()
        if template:
            # ??
            if os.path.exists(template.filepath):
                os.remove(template.filepath)
            # ??
            db.delete(template)
            db.commit()
        
        return {"status": "success"}
    except Exception as e:
        print(f"[ERROR] ??: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/teacher-stats/{teacher_id}")
async def get_teacher_stats(teacher_id: int, db: Session = Depends(get_db)):
    """??"""
    try:
        meetings = db.query(Meeting).filter(Meeting.teacher_id == teacher_id).all()
        meeting_ids = [int(m.id) for m in meetings]
        total_classes = len(meeting_ids)

        total_students = 0
        avg_score = 0
        risk_groups = 0

        if meeting_ids:
            total_students = db.query(
                sa_func.count(sa_func.distinct(Transcript.user_id))
            ).join(
                User, User.id == Transcript.user_id
            ).filter(
                Transcript.meeting_id.in_(meeting_ids),
                User.role != "teacher"
            ).scalar() or 0

            activity_map = _build_meeting_activity_map(db, meeting_ids, exclude_teacher=True)
            total_score = 0
            for meeting_id in meeting_ids:
                activity = activity_map.get(meeting_id, {})
                speech_count = int(activity.get("speech_count", 0))
                member_count = int(activity.get("member_count", 0))
                avg_speech = speech_count / max(member_count, 1)
                base = min(60.0, avg_speech * 12.0)
                volume = min(30.0, speech_count * 0.8)
                breadth = min(10.0, member_count * 1.0)
                score = int(min(100.0, base + volume + breadth))
                total_score += score
                if score < 60:
                    risk_groups += 1

            if total_classes > 0:
                avg_score = int(total_score / total_classes)
        
        return {
            "status": "success",
            "stats": {
                "totalClasses": total_classes,
                "totalStudents": total_students,
                "avgScore": avg_score,
                "riskGroups": risk_groups
            }
        }
    except Exception as e:
        print(f"[ERROR] ??: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/teacher-classes/{teacher_id}")
async def get_teacher_classes(teacher_id: int, db: Session = Depends(get_db)):
    """??"""
    try:
        meetings = db.query(Meeting).filter(
            Meeting.teacher_id == teacher_id
        ).order_by(Meeting.created_at.desc()).all()

        meeting_ids = [int(m.id) for m in meetings]
        activity_map = _build_meeting_activity_map(db, meeting_ids, exclude_teacher=True)
        window_map = _build_meeting_window_map(db, meeting_ids)

        classes = []
        for m in meetings:
            activity = activity_map.get(int(m.id), {})
            speech_count = int(activity.get("speech_count", 0))
            member_count = int(activity.get("member_count", 0))

            avg_speech = speech_count / max(member_count, 1)
            base = min(60.0, avg_speech * 12.0)
            volume = min(30.0, speech_count * 0.8)
            breadth = min(10.0, member_count * 1.0)
            score = int(min(100.0, base + volume + breadth))

            if score >= 80:
                score_level = '优秀'
                score_color = 'green'
            elif score >= 60:
                score_level = '良好'
                score_color = 'yellow'
            else:
                score_level = '待提高'
                score_color = 'red'
            
            window = window_map.get(int(m.id), {})
            first_at = window.get("first_at")
            last_at = window.get("last_at")
            if first_at and last_at:
                duration_minutes = max(0, int((last_at - first_at).total_seconds() / 60))
            else:
                duration_minutes = 0

            classes.append({
                "meeting_id": m.id,
                "class_code": m.class_code,
                "topic": m.topic,
                "status": m.status,
                "member_count": member_count,
                "speech_count": speech_count,
                "duration_minutes": duration_minutes,
                "score": score,
                "score_level": score_level,
                "score_color": score_color,
                "created_at": m.created_at.isoformat()
            })
        
        return {"status": "success", "classes": classes}
    except Exception as e:
        print(f"[ERROR] ??: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/class-groups/{meeting_id}")
async def get_class_groups(meeting_id: int, db: Session = Depends(get_db)):
    """??/??"""
    try:
        meeting = db.query(Meeting).filter(Meeting.id == meeting_id).first()
        if not meeting:
            return {"status": "error", "message": "??"}
        
        # ??
        transcripts = db.query(Transcript).filter(Transcript.meeting_id == meeting_id).all()
        
        # ??
        user_stats = {}
        for t in transcripts:
            user = t.user
            # 教师端查看学生表现时，排除老师账号
            if getattr(user, "role", None) == "teacher":
                continue
            if user.id not in user_stats:
                user_stats[user.id] = {
                    "user_id": user.id,
                    "username": user.username,
                    "speech_count": 0,
                    "total_relevance": 0,
                    "total_quality": 0
                }
            user_stats[user.id]["speech_count"] += 1
            user_stats[user.id]["total_relevance"] += t.relevance_score or 0
            user_stats[user.id]["total_quality"] += t.quality_score or 50
        
        # ??
        groups = []
        for uid, stats in user_stats.items():
            sc = stats["speech_count"]
            avg_relevance = stats["total_relevance"] / sc if sc > 0 else 0
            avg_quality = stats["total_quality"] / sc if sc > 0 else 50
            
            # ??
            score = int(avg_quality * 0.6 + avg_relevance * 0.4)
            
            if score >= 70:
                status = '优秀'
                status_color = 'green'
            elif score >= 50:
                status = '良好'
                status_color = 'yellow'
            else:
                status = '待提高'
                status_color = 'red'
            
            groups.append({
                "user_id": uid,
                "username": stats["username"],
                "speech_count": sc,
                "avg_relevance": round(avg_relevance, 1),
                "avg_quality": round(avg_quality, 1),
                "score": score,
                "status": status,
                "status_color": status_color
            })
        
        # ??
        groups.sort(key=lambda x: x["score"])
        
        return {
            "status": "success",
            "meeting_topic": meeting.topic,
            "groups": groups
        }
    except Exception as e:
        print(f"[ERROR] ??: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/all-student-reports/{teacher_id}")
async def get_all_student_reports(teacher_id: int, db: Session = Depends(get_db)):
    """??"""
    try:
        # ??
        meetings = db.query(Meeting).filter(Meeting.teacher_id == teacher_id).all()
        meeting_ids = [m.id for m in meetings]
        meeting_map = {m.id: m for m in meetings}
        
        if not meeting_ids:
            return {"status": "success", "reports": []}
        
        # ??
        reports = db.query(LearningReport).filter(
            LearningReport.meeting_id.in_(meeting_ids)
        ).order_by(LearningReport.created_at.desc()).all()
        
        result = []
        for r in reports:
            user = db.query(User).filter(User.id == r.user_id).first()
            meeting = meeting_map.get(r.meeting_id)

            data = r.report_data or {}

            # 从数据库实时查询真实的发言数（整个会议的累计值，而非窗口增量）
            real_speech_count = db.query(Transcript).filter(
                Transcript.meeting_id == r.meeting_id,
                Transcript.user_id == r.user_id
            ).count()
            # 如果按user_id查不到，尝试按用户名查
            if real_speech_count == 0 and user:
                real_speech_count = db.query(Transcript).join(User).filter(
                    Transcript.meeting_id == r.meeting_id,
                    User.username == user.username
                ).count()

            # 查询真实的习题数
            exercise_count = db.query(Exercise).filter(Exercise.report_id == r.id).count()

            # 计算真实的专注度（平均相关度）
            from sqlalchemy import func as sa_func
            avg_rel_result = db.query(sa_func.avg(Transcript.relevance_score)).filter(
                Transcript.meeting_id == r.meeting_id,
                Transcript.user_id == r.user_id,
                Transcript.relevance_score > 0
            ).scalar()
            real_avg_relevance = round(avg_rel_result, 1) if avg_rel_result else data.get("avg_relevance", 0)

            result.append({
                "report_id": r.id,
                "meeting_id": r.meeting_id,
                "user_id": r.user_id,
                "class_code": meeting.class_code if meeting else "",
                "topic": meeting.topic if meeting else "",
                "student_name": user.username if user else "未知",
                "student_id": user.student_id if user else "",
                "speech_count": real_speech_count or data.get("speech_count", 0),
                "exercise_count": exercise_count,
                "avg_relevance": real_avg_relevance,
                "summary": data.get("course_summary", "")[:100] + "..." if data.get("course_summary") else "",
                "created_at": r.created_at.isoformat()
            })
        
        return {"status": "success", "reports": result}
    except Exception as e:
        print(f"[ERROR] ??: {e}")
        return {"status": "error", "message": str(e)}


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

@app.get("/voiceprint_register")
async def voiceprint_register_page():
    """声纹注册页面"""
    return FileResponse("voiceprint_register.html")


@app.post("/api/voiceprint/register")
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


@app.post("/api/voiceprint/verify")
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


@app.get("/api/voiceprint/status/{username}")
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


@app.delete("/api/voiceprint/unregister/{username}")
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


@app.get("/api/voiceprint/users")
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


@app.post("/api/voiceprint/identify")
async def identify_speaker(audio: UploadFile = File(...)):
    """
    从所有已注册用户中识别说话人

    Args:
        audio: 音频文件
    """
    try:
        # 保存临时文件
        temp_audio_path = f"storage/temp_identify_{audio.filename}"
        os.makedirs("storage", exist_ok=True)

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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
