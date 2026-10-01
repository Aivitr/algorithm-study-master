"""实时链路的**进程内共享状态**与调参常量。

本模块持有四份被多处代码共享的可变状态：

    kg_counter                   {meeting_id: 计数}，每 N 次触达就重建知识图谱
    recent_speech_cache          {(meeting_id, 归一化文本): 发言}，跨端短时去重
    recent_media_state           {(meeting_id, 用户名): 最近一次音视频资产}
    recent_speech_cache_lock /
    recent_media_state_lock      上面两者的锁

它们必须始终是**同一个对象**：只许就地修改，不能重新绑定，否则别处的调用点看到
的就不是同一份数据。

下面紧跟着短时缓存的自洽辅助（`_normalize_transcript_text`、
`_transcript_text_similar`、`_mark_recent_speech`、`_reserve_recent_speech_by_volume`、
`_attach_recent_speech_transcript`、`_remember/_get_recent_media_state`、
`_split_realtime_sentences` 等），与上面那几张表是一体的，不要拆开。

`ASR_*` / `REALTIME_*` 常量是这一整套的调参项。

`ROOT_DIR` 来自 `app.core.paths.PROJECT_ROOT`，`_storage_relative_path` 的相对路径
换算以它为基准。
"""

import os
import re
import shutil
import threading
import time
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from app.core.emotions import normalize_emotion_label
from app.core.paths import PROJECT_ROOT

ROOT_DIR = str(PROJECT_ROOT)  # 项目根目录

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
ASR_SELF_VOICE_GATE_ENABLED = False  # 关闭声纹门控，允许所有用户语音转文字
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
