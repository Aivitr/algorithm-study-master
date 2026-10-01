# -*- coding: utf-8 -*-
"""Local voiceprint registration and matching.

Keeps the same public API while using:
- Resemblyzer preprocessing/VAD before embedding.
- Multiple enrollment embeddings when the recording is long enough.
- Multi-window verification with a stability check.
- Top-1 / top-2 margin checks when more than one user is registered.
"""

import json
import logging
import os
import tempfile
import time
from typing import Dict, List, Optional, Tuple

import librosa
import numpy as np
import requests
from resemblyzer import VoiceEncoder, preprocess_wav

logger = logging.getLogger(__name__)

VOICE_SAMPLE_RATE = 16000
MIN_AUDIO_SECONDS = 1.4
WINDOW_SECONDS = 2.4
WINDOW_STRIDE_SECONDS = 1.2
MAX_EMBEDDINGS_PER_SAMPLE = 5
DEFAULT_DISTANCE_THRESHOLD = 0.24
AMBIGUOUS_MARGIN = 0.035


class VoiceprintManager:
    """Manage local voiceprints."""

    def __init__(self, db_path: str = "voiceprints.json"):
        self.db_path = db_path
        self.encoder = VoiceEncoder()
        self.voiceprints_db: Dict[str, object] = {}
        self.load_database()
        logger.info("[voiceprint] loaded %s registered users", len(self.voiceprints_db))

    def load_database(self):
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    self.voiceprints_db = json.load(f)
            except Exception as e:
                logger.error("[voiceprint] failed to load database: %s", e)
                self.voiceprints_db = {}
        else:
            self.voiceprints_db = {}

    def save_database(self):
        try:
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(self.voiceprints_db, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("[voiceprint] failed to save database: %s", e)

    def _download_audio_from_url(self, url: str) -> str:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        suffix = ".wav"
        if "." in url:
            suffix = "." + url.split(".")[-1].split("?")[0]
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        temp_file.write(response.content)
        temp_file.close()
        return temp_file.name

    def _load_audio(self, audio_path: str) -> np.ndarray:
        # preprocess_wav performs resampling, normalization, and silence trimming.
        try:
            audio = preprocess_wav(audio_path)
        except Exception:
            audio, _ = librosa.load(audio_path, sr=VOICE_SAMPLE_RATE, mono=True)
            audio = np.asarray(audio, dtype=np.float32)

        if audio is None:
            return np.array([], dtype=np.float32)
        audio = np.asarray(audio, dtype=np.float32)
        audio = audio[np.isfinite(audio)]
        if audio.size:
            peak = float(np.max(np.abs(audio)))
            if peak > 1.0:
                audio = audio / peak
        return audio

    def _audio_quality_ok(self, audio: np.ndarray) -> Tuple[bool, str]:
        duration = len(audio) / float(VOICE_SAMPLE_RATE)
        if duration < MIN_AUDIO_SECONDS:
            return False, f"audio too short after trimming: {duration:.2f}s"
        rms = float(np.sqrt(np.mean(np.square(audio.astype(np.float64))))) if len(audio) else 0.0
        if rms < 0.008:
            return False, "audio is too quiet or mostly silence"
        return True, ""

    def _make_windows(self, audio: np.ndarray) -> List[np.ndarray]:
        min_len = int(MIN_AUDIO_SECONDS * VOICE_SAMPLE_RATE)
        win_len = int(WINDOW_SECONDS * VOICE_SAMPLE_RATE)
        stride = int(WINDOW_STRIDE_SECONDS * VOICE_SAMPLE_RATE)
        windows: List[np.ndarray] = []

        if len(audio) < min_len:
            return windows

        windows.append(audio)
        if len(audio) >= win_len:
            starts = list(range(0, max(1, len(audio) - win_len + 1), max(1, stride)))
            if starts and starts[-1] != len(audio) - win_len:
                starts.append(len(audio) - win_len)
            if len(starts) > MAX_EMBEDDINGS_PER_SAMPLE - 1:
                picks = np.linspace(0, len(starts) - 1, MAX_EMBEDDINGS_PER_SAMPLE - 1).round().astype(int)
                starts = [starts[i] for i in sorted(set(picks.tolist()))]
            for start in starts:
                segment = audio[start:start + win_len]
                if len(segment) >= min_len:
                    windows.append(segment)

        return windows[:MAX_EMBEDDINGS_PER_SAMPLE]

    def _embed_audio(self, audio: np.ndarray) -> np.ndarray:
        windows = self._make_windows(audio)
        embeddings = []
        for window in windows:
            emb = self.encoder.embed_utterance(window)
            emb = np.asarray(emb, dtype=np.float32)
            norm = np.linalg.norm(emb)
            if norm > 0:
                emb = emb / norm
            embeddings.append(emb)
        if not embeddings:
            return np.empty((0, 0), dtype=np.float32)
        return np.vstack(embeddings)

    def _entry_embeddings(self, username: str) -> np.ndarray:
        entry = self.voiceprints_db.get(username)
        if entry is None:
            return np.empty((0, 0), dtype=np.float32)

        if isinstance(entry, dict):
            raw = entry.get("embeddings") or entry.get("voiceprints") or entry.get("embedding")
        else:
            raw = entry

        arr = np.asarray(raw, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        if arr.ndim != 2 or arr.shape[1] == 0:
            return np.empty((0, 0), dtype=np.float32)

        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return arr / norms

    def _score_against_user(self, test_embeddings: np.ndarray, username: str) -> Dict[str, float]:
        enrolled = self._entry_embeddings(username)
        if test_embeddings.size == 0 or enrolled.size == 0:
            return {
                "similarity": 0.0,
                "distance": 1.0,
                "median_distance": 1.0,
                "pass_ratio": 0.0,
            }

        sims = np.matmul(test_embeddings, enrolled.T)
        best_per_window = np.max(sims, axis=1)
        distances = 1.0 - best_per_window
        return {
            "similarity": float(np.max(best_per_window)),
            "distance": float(np.min(distances)),
            "median_distance": float(np.median(distances)),
            "pass_ratio": 0.0,
        }

    def _rank_users(self, test_embeddings: np.ndarray) -> List[Tuple[str, Dict[str, float]]]:
        results = []
        for username in self.voiceprints_db.keys():
            score = self._score_against_user(test_embeddings, username)
            results.append((username, score))
        results.sort(key=lambda item: (item[1]["median_distance"], item[1]["distance"]))
        return results

    def _is_stable_match(
        self,
        target_score: Dict[str, float],
        threshold: float,
        window_count: int,
    ) -> bool:
        best_distance = target_score["distance"]
        median_distance = target_score["median_distance"]
        if best_distance > threshold:
            return False
        if window_count <= 1:
            return True
        # A single lucky window is not enough. Most windows must remain close.
        return median_distance <= threshold + 0.045

    def register_voiceprint(self, username: str, audio_path: str) -> Tuple[bool, str]:
        temp_file = None
        try:
            if audio_path.startswith("http://") or audio_path.startswith("https://"):
                temp_file = self._download_audio_from_url(audio_path)
                audio_path = temp_file

            audio = self._load_audio(audio_path)
            ok, reason = self._audio_quality_ok(audio)
            if not ok:
                return False, f"声纹样本质量不够：{reason}，请靠近麦克风录制 4-8 秒清晰语音"

            embeddings = self._embed_audio(audio)
            if embeddings.size == 0:
                return False, "声纹特征提取失败，请重新录制"

            self.voiceprints_db[username] = {
                "version": 2,
                "created_at": int(time.time()),
                "duration_seconds": round(len(audio) / float(VOICE_SAMPLE_RATE), 2),
                "embeddings": embeddings.tolist(),
            }
            self.save_database()
            logger.info(
                "[voiceprint] registered %s, duration=%.2fs, embeddings=%s",
                username,
                len(audio) / float(VOICE_SAMPLE_RATE),
                embeddings.shape[0],
            )
            return True, "声纹注册成功"
        except Exception as e:
            logger.error("[voiceprint] register failed for %s: %s", username, e)
            return False, f"注册失败: {str(e)}"
        finally:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except Exception:
                    pass

    def verify_voiceprint(
        self,
        username: str,
        audio_path: str,
        threshold: float = DEFAULT_DISTANCE_THRESHOLD,
    ) -> Tuple[bool, float, float]:
        try:
            if username not in self.voiceprints_db:
                return False, 0.0, 1.0

            audio = self._load_audio(audio_path)
            ok, _ = self._audio_quality_ok(audio)
            if not ok:
                return False, 0.0, 1.0

            test_embeddings = self._embed_audio(audio)
            if test_embeddings.size == 0:
                return False, 0.0, 1.0

            ranks = self._rank_users(test_embeddings)
            target_score = self._score_against_user(test_embeddings, username)
            is_match = self._is_stable_match(target_score, threshold, len(test_embeddings))

            if ranks:
                best_user, best_score = ranks[0]
                if best_user != username:
                    is_match = False
                elif len(ranks) > 1:
                    second_distance = ranks[1][1]["median_distance"]
                    margin = second_distance - best_score["median_distance"]
                    if margin < AMBIGUOUS_MARGIN:
                        is_match = False

            confidence = max(0.0, min(1.0, 1.0 - target_score["median_distance"]))
            distance = target_score["median_distance"]
            logger.info(
                "[voiceprint] verify %s match=%s distance=%.3f confidence=%.3f windows=%s",
                username,
                is_match,
                distance,
                confidence,
                len(test_embeddings),
            )
            return bool(is_match), float(confidence), float(distance)
        except Exception as e:
            logger.error("[voiceprint] verify failed for %s: %s", username, e)
            return False, 0.0, 1.0

    def match_voiceprint(
        self,
        audio_data: np.ndarray,
        target_username: str,
        threshold: float = DEFAULT_DISTANCE_THRESHOLD,
    ) -> Tuple[bool, float]:
        try:
            audio = np.asarray(audio_data, dtype=np.float32)
            if audio.size and np.max(np.abs(audio)) > 2:
                audio = audio / 32768.0
            ok, _ = self._audio_quality_ok(audio)
            if not ok:
                return False, 0.0
            test_embeddings = self._embed_audio(audio)
            target_score = self._score_against_user(test_embeddings, target_username)
            is_match = self._is_stable_match(target_score, threshold, len(test_embeddings))
            confidence = max(0.0, min(1.0, 1.0 - target_score["median_distance"]))
            return bool(is_match), float(confidence)
        except Exception as e:
            logger.error("[voiceprint] match failed for %s: %s", target_username, e)
            return False, 0.0

    def unregister_voiceprint(self, username: str) -> Tuple[bool, str]:
        try:
            if username in self.voiceprints_db:
                del self.voiceprints_db[username]
                self.save_database()
                return True, "声纹删除成功"
            return False, "用户未注册声纹"
        except Exception as e:
            logger.error("[voiceprint] unregister failed for %s: %s", username, e)
            return False, f"删除失败: {str(e)}"

    def is_registered(self, username: str) -> bool:
        return username in self.voiceprints_db and self._entry_embeddings(username).size > 0

    def get_all_users(self) -> list:
        return list(self.voiceprints_db.keys())

    def identify_speaker(
        self,
        audio_path: str,
        threshold: float = DEFAULT_DISTANCE_THRESHOLD,
    ) -> Tuple[Optional[str], float, float]:
        try:
            if not self.voiceprints_db:
                return None, 0.0, 1.0

            audio = self._load_audio(audio_path)
            ok, _ = self._audio_quality_ok(audio)
            if not ok:
                return None, 0.0, 1.0

            test_embeddings = self._embed_audio(audio)
            ranks = self._rank_users(test_embeddings)
            if not ranks:
                return None, 0.0, 1.0

            best_user, best_score = ranks[0]
            best_distance = best_score["median_distance"]
            confidence = max(0.0, min(1.0, 1.0 - best_distance))
            if not self._is_stable_match(best_score, threshold, len(test_embeddings)):
                return None, float(confidence), float(best_distance)

            if len(ranks) > 1:
                second_distance = ranks[1][1]["median_distance"]
                if (second_distance - best_distance) < AMBIGUOUS_MARGIN:
                    return None, float(confidence), float(best_distance)

            return best_user, float(confidence), float(best_distance)
        except Exception as e:
            logger.error("[voiceprint] identify failed: %s", e)
            return None, 0.0, 1.0


voiceprint_manager = VoiceprintManager()
