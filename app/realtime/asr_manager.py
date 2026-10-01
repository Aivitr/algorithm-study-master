"""阿里云 NLS 实时转写会话管理。

`ASRSessionManager` 为每个用户维护一条实时转写会话：PCM 音频从前端流入，
识别结果广播给课堂所有成员。它还持有若干**进程内**状态（声纹身份缓存、
自我语音门禁状态、句子级音量竞争、句子合并缓冲），是长生命周期的单例——
文件末尾的 `asr_manager = ASRSessionManager()`。

`asr_manager` 必须自始至终是**同一个对象**，各调用点都从这里取，不要重新构造，
否则会出现"某人说话时另一处查不到他的会话"且不报错。

## 关于这堆 import

模块级全局必须显式、完整地导入，少一个要到执行到那条分支才 NameError。
`tests_safe/test_module_free_names.py` 用 symtable 判据守住这一点，本模块的头
必须让它保持空集。
"""

import asyncio
import os
import re
import threading
import time
import wave
from collections import deque
from typing import Any, Dict, List, Optional

import numpy as np

from app.core.paths import PROJECT_ROOT
from app.realtime.registry import manager
from app.realtime.speech import (
    _create_realtime_transcript_entry,
    _run_realtime_speech_analysis,
    _stream_realtime_speech_analysis_events,
)
from app.realtime.state import (
    ASR_REQUIRE_VOICEPRINT_IDENTITY,
    ASR_SELF_VOICE_GATE_ENABLED,
    ASR_SELF_VOICE_GATE_THRESHOLD,
    ASR_SENTENCE_END_SILENCE_SECONDS,
    ASR_SPEAKER_CACHE_MAX_HITS,
    ASR_SPEAKER_CACHE_TTL_SECONDS,
    ASR_UNKNOWN_SPEAKER_LABEL,
    REALTIME_ASR_VOICEPRINT_DISABLED,
)
from app.services.voiceprint_manager import voiceprint_manager

# 直接由 PROJECT_ROOT 重算，不复制字面量路径，免得锚点随文件位置漂移
# （见 tests_safe/test_paths_anchor.py）。
ROOT_DIR = str(PROJECT_ROOT)

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

        # 关闭声纹门控检查，允许所有语音转文字输出
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
                # 关闭声纹门控检查，允许所有语音转文字输出
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
            # 标准方案
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
