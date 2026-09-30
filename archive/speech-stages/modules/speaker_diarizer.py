# -*- coding: utf-8 -*-
"""
说话人识别和区分模块（Speaker Diarization）

功能:
1. 实时识别和区分不同说话人
2. 给每个转录文本标记说话人 ID
3. 支持多说话人场景的课堂转录

集成到 ai_core.py 的 RealtimeTranscriber 中
"""

import json
import numpy as np
import hashlib
from typing import Dict, List, Tuple, Optional, Any
from collections import defaultdict
from dataclasses import dataclass, asdict
import threading
import time


@dataclass
class SpeakerSegment:
    """说话人分段"""
    speaker_id: int
    speaker_name: Optional[str]
    text: str
    start_time: float
    end_time: float
    confidence: float
    emotion: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SpeakerDiarizer:
    """
    说话人区分器
    
    基于音频信号特征（音高、频谱、节奏等）识别不同说话人
    """

    def __init__(self, num_speakers: Optional[int] = None):
        """
        初始化说话人区分器
        
        Args:
            num_speakers: 预期的说话人数量（可选，如果为 None 则自动检测）
        """
        self.num_speakers = num_speakers
        self.speaker_embeddings: Dict[int, np.ndarray] = {}
        self.speaker_names: Dict[int, str] = {}
        self.speaker_count = 0
        self.segments: List[SpeakerSegment] = []
        self.lock = threading.Lock()

        # 音频特征缓存
        self.feature_buffer = []
        self.current_time = 0.0

    def register_speaker(self, speaker_name: str) -> int:
        """
        注册说话人
        
        Args:
            speaker_name: 说话人名称（如学生名字或角色）
            
        Returns:
            speaker_id: 分配的说话人 ID
        """
        with self.lock:
            speaker_id = self.speaker_count
            self.speaker_names[speaker_id] = speaker_name
            self.speaker_count += 1
            print(f"[Speaker] 已注册说话人: {speaker_name} (ID: {speaker_id})")
            return speaker_id

    def extract_audio_features(self, pcm_chunk: bytes, sample_rate: int = 16000) -> Dict[str, np.ndarray]:
        """
        从 PCM 音频数据中提取特征
        
        Args:
            pcm_chunk: PCM 字节数据（16-bit）
            sample_rate: 采样率
            
        Returns:
            特征字典
        """
        # 转换字节为 numpy 数组（16-bit PCM）
        audio = np.frombuffer(pcm_chunk, dtype=np.int16).astype(np.float32) / 32768.0

        features = {}

        # 1. 能量特征
        energy = np.sqrt(np.mean(audio ** 2))
        features["energy"] = energy

        # 2. 零交叉率（ZCR）- 可用于语音/非语音检测
        zcr = np.mean(np.abs(np.diff(np.sign(audio))))
        features["zcr"] = zcr

        # 3. 音高特征（基频估计）
        # 简化版本：使用自相关方法
        if len(audio) > 512:
            autocorr = np.correlate(audio, audio, mode='full')
            autocorr = autocorr[len(autocorr) // 2:]
            # 找到主要峰值（代表基频）
            try:
                peaks = np.argsort(autocorr)[-3:]  # 取前3个峰值
                if len(peaks) > 1:
                    f0_index = peaks[-2]  # 第二个峰值通常是基频
                    f0_hz = sample_rate / f0_index if f0_index > 0 else 0
                    features["pitch"] = f0_hz
                else:
                    features["pitch"] = 0
            except:
                features["pitch"] = 0

        # 4. MFCC-like 特征（简化版）
        # 计算频域特征
        try:
            # 简单的 FFT 分析
            fft = np.abs(np.fft.rfft(audio))
            # 分频段统计
            features["low_freq_energy"] = np.mean(fft[:len(fft)//4])
            features["mid_freq_energy"] = np.mean(fft[len(fft)//4:len(fft)//2])
            features["high_freq_energy"] = np.mean(fft[len(fft)//2:])
        except:
            features["low_freq_energy"] = 0
            features["mid_freq_energy"] = 0
            features["high_freq_energy"] = 0

        return features

    def get_speaker_from_features(self, features: Dict[str, np.ndarray]) -> Tuple[int, float]:
        """
        基于音频特征识别说话人
        
        Args:
            features: 音频特征
            
        Returns:
            (speaker_id, confidence) 元组
        """
        with self.lock:
            if not self.speaker_embeddings:
                # 如果没有已知说话人，则创建新说话人
                # 这在第一次或多说话人场景中会发生
                new_speaker_id = len(self.speaker_names)
                # 生成说话人名称
                speaker_name = f"说话人_{new_speaker_id + 1}"
                self.speaker_names[new_speaker_id] = speaker_name
                self.speaker_embeddings[new_speaker_id] = self._features_to_embedding(features)
                return new_speaker_id, 0.8

            # 计算特征向量
            current_embedding = self._features_to_embedding(features)

            # 与已知说话人比较
            best_speaker_id = 0
            best_similarity = -1

            for speaker_id, speaker_embedding in self.speaker_embeddings.items():
                similarity = self._cosine_similarity(current_embedding, speaker_embedding)
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_speaker_id = speaker_id

            # 如果相似度过低，可能是新说话人
            similarity_threshold = 0.6
            if best_similarity < similarity_threshold and len(self.speaker_embeddings) < (self.num_speakers or 10):
                new_speaker_id = len(self.speaker_names)
                speaker_name = f"说话人_{new_speaker_id + 1}"
                self.speaker_names[new_speaker_id] = speaker_name
                self.speaker_embeddings[new_speaker_id] = current_embedding
                return new_speaker_id, 0.7
            else:
                # 更新该说话人的特征（平均）
                alpha = 0.1  # 更新率
                self.speaker_embeddings[best_speaker_id] = (
                    (1 - alpha) * self.speaker_embeddings[best_speaker_id] +
                    alpha * current_embedding
                )
                return best_speaker_id, max(0.5, min(1.0, best_similarity))

    def _features_to_embedding(self, features: Dict[str, np.ndarray]) -> np.ndarray:
        """将特征转换为嵌入向量"""
        embedding = np.array([
            features.get("energy", 0),
            features.get("zcr", 0),
            features.get("pitch", 0) / 200.0,  # 归一化
            features.get("low_freq_energy", 0),
            features.get("mid_freq_energy", 0),
            features.get("high_freq_energy", 0),
        ])
        # 归一化
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """计算余弦相似度"""
        try:
            dot_product = np.dot(a, b)
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)
            if norm_a > 0 and norm_b > 0:
                return dot_product / (norm_a * norm_b)
            return 0.0
        except:
            return 0.0

    def add_segment(self, speaker_id: int, text: str, duration: float = 1.0, emotion: Optional[str] = None):
        """
        添加说话人分段
        
        Args:
            speaker_id: 说话人 ID
            text: 文本内容
            duration: 分段时长（秒）
            emotion: 情感标签（可选）
        """
        with self.lock:
            start_time = self.current_time
            end_time = start_time + duration
            self.current_time = end_time

            speaker_name = self.speaker_names.get(speaker_id, f"说话人_{speaker_id}")

            segment = SpeakerSegment(
                speaker_id=speaker_id,
                speaker_name=speaker_name,
                text=text,
                start_time=start_time,
                end_time=end_time,
                confidence=0.85,
                emotion=emotion
            )

            self.segments.append(segment)
            return segment

    def get_transcript_with_speakers(self) -> List[Dict[str, Any]]:
        """
        获取带有说话人标记的完整转录
        
        Returns:
            分段列表，每个分段包含说话人信息
        """
        with self.lock:
            return [segment.to_dict() for segment in self.segments]

    def get_speaker_stats(self) -> Dict[str, Any]:
        """
        获取说话人统计信息
        
        Returns:
            统计数据字典
        """
        with self.lock:
            stats = {
                "total_speakers": len(self.speaker_names),
                "total_segments": len(self.segments),
                "speakers": {}
            }

            for speaker_id, speaker_name in self.speaker_names.items():
                speaker_segments = [s for s in self.segments if s.speaker_id == speaker_id]
                total_text = "".join([s.text for s in speaker_segments])
                total_duration = sum([s.end_time - s.start_time for s in speaker_segments])

                stats["speakers"][speaker_id] = {
                    "name": speaker_name,
                    "segment_count": len(speaker_segments),
                    "total_duration": total_duration,
                    "text_length": len(total_text),
                    "avg_confidence": np.mean([s.confidence for s in speaker_segments]) if speaker_segments else 0
                }

            return stats

    def export_to_json(self, filename: str):
        """
        导出转录为 JSON 格式
        
        Args:
            filename: 输出文件名
        """
        with self.lock:
            data = {
                "speakers": [],
                "segments": [],
                "statistics": self.get_speaker_stats()
            }

            for speaker_id, speaker_name in self.speaker_names.items():
                data["speakers"].append({
                    "id": speaker_id,
                    "name": speaker_name
                })

            for segment in self.segments:
                data["segments"].append(segment.to_dict())

            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            print(f"[Speaker] 转录已导出到: {filename}")

    def export_to_srt(self, filename: str):
        """
        导出为 SRT 字幕格式
        
        Args:
            filename: 输出文件名
        """
        with self.lock:
            with open(filename, "w", encoding="utf-8") as f:
                for i, segment in enumerate(self.segments, 1):
                    # SRT 格式：序号、时间范围、内容
                    start = self._seconds_to_srt_time(segment.start_time)
                    end = self._seconds_to_srt_time(segment.end_time)
                    speaker_label = segment.speaker_name or f"Speaker {segment.speaker_id}"

                    f.write(f"{i}\n")
                    f.write(f"{start} --> {end}\n")
                    f.write(f"[{speaker_label}] {segment.text}\n")
                    f.write("\n")

            print(f"[Speaker] 字幕已导出到: {filename}")

    @staticmethod
    def _seconds_to_srt_time(seconds: float) -> str:
        """将秒数转换为 SRT 时间格式"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def reset(self):
        """重置所有分段和状态"""
        with self.lock:
            self.segments = []
            self.current_time = 0.0
            # 保留已注册的说话人


# 全局说话人区分器实例
_global_diarizer: Optional[SpeakerDiarizer] = None
_diarizer_lock = threading.Lock()


def get_diarizer(num_speakers: Optional[int] = None) -> SpeakerDiarizer:
    """获取全局说话人区分器实例"""
    global _global_diarizer
    with _diarizer_lock:
        if _global_diarizer is None:
            _global_diarizer = SpeakerDiarizer(num_speakers=num_speakers)
        return _global_diarizer


def reset_global_diarizer():
    """重置全局说话人区分器"""
    global _global_diarizer
    with _diarizer_lock:
        if _global_diarizer:
            _global_diarizer.reset()
