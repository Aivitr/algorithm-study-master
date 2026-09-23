"""
带声纹验证的实时语音转写器
在多人环境中精准识别单个用户的声音
"""
import os
import time
import wave
import tempfile
import threading
from typing import Optional, Callable
from ai_core import RealtimeTranscriber
from voiceprint_service import voiceprint_service


class VoiceprintRealtimeTranscriber(RealtimeTranscriber):
    """
    增强版实时转写器，支持声纹验证

    工作流程：
    1. 接收音频流 → 缓存音频片段
    2. 每个片段进行声纹验证
    3. 只有匹配用户声纹的片段才会转写
    4. 过滤掉其他人的声音
    """

    def __init__(
        self,
        username: str,
        on_partial: Optional[Callable] = None,
        on_final: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        voiceprint_threshold: float = 0.25,
        enable_voiceprint: bool = True,
        buffer_duration: float = 1.0,  # 缓冲时长（秒）
    ):
        """
        Args:
            username: 用户名（用于声纹匹配）
            voiceprint_threshold: 声纹匹配阈值（0.2-0.3 推荐）
            enable_voiceprint: 是否启用声纹验证
            buffer_duration: 音频缓冲时长，用于声纹验证
        """
        super().__init__(on_partial, on_final, on_error)

        self.username = username
        self.voiceprint_threshold = voiceprint_threshold
        self.enable_voiceprint = enable_voiceprint
        self.buffer_duration = buffer_duration

        # 音频缓冲区（用于声纹验证）
        self.audio_buffer = []
        self.buffer_lock = threading.Lock()
        self.buffer_size = int(16000 * 2 * buffer_duration)  # 16kHz, 16-bit

        # 统计信息
        self.total_chunks = 0
        self.verified_chunks = 0
        self.rejected_chunks = 0

        # 检查用户是否注册声纹
        self.user_registered = voiceprint_service.is_user_registered(username)
        if self.enable_voiceprint and not self.user_registered:
            print(f"[WARN] 用户 {username} 未注册声纹，声纹验证将被跳过")
            self.enable_voiceprint = False

    def feed_audio(self, pcm_chunk: bytes):
        """
        输入音频数据，带声纹验证

        Args:
            pcm_chunk: 16kHz 16-bit 单声道 PCM 数据
        """
        self.total_chunks += 1

        # 如果未启用声纹验证，直接转发
        if not self.enable_voiceprint:
            super().feed_audio(pcm_chunk)
            self.verified_chunks += 1
            return

        # 添加到缓冲区
        with self.buffer_lock:
            self.audio_buffer.append(pcm_chunk)
            buffer_bytes = b''.join(self.audio_buffer)

            # 缓冲区达到指定大小时进行声纹验证
            if len(buffer_bytes) >= self.buffer_size:
                # 验证声纹
                if self._verify_buffer(buffer_bytes):
                    # 验证通过，转发所有缓冲的音频
                    for chunk in self.audio_buffer:
                        super().feed_audio(chunk)
                    self.verified_chunks += len(self.audio_buffer)
                else:
                    # 验证失败，丢弃缓冲区
                    self.rejected_chunks += len(self.audio_buffer)
                    print(f"[VOICEPRINT] 检测到非目标用户声音，已过滤 {len(self.audio_buffer)} 个音频块")

                # 清空缓冲区
                self.audio_buffer.clear()

    def _verify_buffer(self, audio_bytes: bytes) -> bool:
        """
        验证缓冲区音频是否为目标用户

        Args:
            audio_bytes: PCM 音频数据

        Returns:
            True 表示是目标用户，False 表示不是
        """
        try:
            # 保存为临时 WAV 文件
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
                tmp_path = tmp_file.name

                # 写入 WAV 文件
                with wave.open(tmp_path, 'wb') as wf:
                    wf.setnchannels(1)  # 单声道
                    wf.setsampwidth(2)  # 16-bit
                    wf.setframerate(16000)  # 16kHz
                    wf.writeframes(audio_bytes)

            # 进行声纹验证
            result = voiceprint_service.verify_speaker(
                self.username,
                tmp_path,
                threshold=self.voiceprint_threshold
            )

            # 删除临时文件
            try:
                os.unlink(tmp_path)
            except:
                pass

            is_match = result.get("is_match", False)
            confidence = result.get("confidence", 0.0)

            if is_match:
                print(f"[VOICEPRINT] ✓ 用户 {self.username} 声纹匹配 (置信度: {confidence:.2f})")
            else:
                print(f"[VOICEPRINT] ✗ 检测到其他人声音 (置信度: {confidence:.2f})")

            return is_match

        except Exception as e:
            print(f"[ERROR] 声纹验证失败: {e}")
            # 验证失败时，默认通过（避免误杀）
            return True

    def stop(self):
        """停止转写并输出统计信息"""
        super().stop()

        if self.enable_voiceprint and self.total_chunks > 0:
            pass_rate = (self.verified_chunks / self.total_chunks) * 100
            print(f"[VOICEPRINT] 统计: 总计 {self.total_chunks} 块, "
                  f"通过 {self.verified_chunks} 块, "
                  f"过滤 {self.rejected_chunks} 块, "
                  f"通过率 {pass_rate:.1f}%")


class VoiceprintRealtimeTranscriberV2(RealtimeTranscriber):
    """
    声纹验证实时转写器 V2 版本

    改进策略：
    - 使用 VAD（语音活动检测）先判断是否有人说话
    - 只对有效语音段进行声纹验证
    - 减少计算开销，提高实时性
    """

    def __init__(
        self,
        username: str,
        on_partial: Optional[Callable] = None,
        on_final: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        voiceprint_threshold: float = 0.25,
        enable_voiceprint: bool = True,
        vad_threshold: int = 500,  # VAD 阈值
    ):
        super().__init__(on_partial, on_final, on_error)

        self.username = username
        self.voiceprint_threshold = voiceprint_threshold
        self.enable_voiceprint = enable_voiceprint
        self.vad_threshold = vad_threshold

        # 音频缓冲
        self.audio_buffer = []
        self.buffer_lock = threading.Lock()
        self.buffer_size = int(16000 * 2 * 1.5)  # 1.5秒缓冲

        # 验证状态缓存（避免频繁验证）
        self.last_verification_result = True
        self.last_verification_time = 0
        self.verification_cache_duration = 3.0  # 缓存3秒

        # 检查用户声纹
        self.user_registered = voiceprint_service.is_user_registered(username)
        if self.enable_voiceprint and not self.user_registered:
            print(f"[WARN] 用户 {username} 未注册声纹，声纹验证已禁用")
            self.enable_voiceprint = False

    def _has_speech(self, audio_bytes: bytes) -> bool:
        """简单的 VAD 检测"""
        import numpy as np
        try:
            data = np.frombuffer(audio_bytes, dtype=np.int16)
            if len(data) == 0:
                return False
            rms = np.sqrt(np.mean(data.astype(np.float64) ** 2))
            return rms > self.vad_threshold
        except:
            return True

    def feed_audio(self, pcm_chunk: bytes):
        """带 VAD 和声纹验证的音频输入"""
        if not self.enable_voiceprint:
            super().feed_audio(pcm_chunk)
            return

        with self.buffer_lock:
            self.audio_buffer.append(pcm_chunk)
            buffer_bytes = b''.join(self.audio_buffer)

            if len(buffer_bytes) >= self.buffer_size:
                # 先进行 VAD 检测
                if not self._has_speech(buffer_bytes):
                    # 静音段，直接丢弃
                    self.audio_buffer.clear()
                    return

                # 检查验证缓存
                current_time = time.time()
                if (current_time - self.last_verification_time) < self.verification_cache_duration:
                    # 使用缓存的验证结果
                    should_pass = self.last_verification_result
                else:
                    # 进行新的声纹验证
                    should_pass = self._verify_buffer(buffer_bytes)
                    self.last_verification_result = should_pass
                    self.last_verification_time = current_time

                if should_pass:
                    # 转发音频
                    for chunk in self.audio_buffer:
                        super().feed_audio(chunk)
                else:
                    print(f"[VOICEPRINT] 过滤非目标用户音频")

                self.audio_buffer.clear()

    def _verify_buffer(self, audio_bytes: bytes) -> bool:
        """声纹验证"""
        try:
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
                tmp_path = tmp_file.name
                with wave.open(tmp_path, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(audio_bytes)

            result = voiceprint_service.verify_speaker(
                self.username,
                tmp_path,
                threshold=self.voiceprint_threshold
            )

            try:
                os.unlink(tmp_path)
            except:
                pass

            return result.get("is_match", True)
        except Exception as e:
            print(f"[ERROR] 声纹验证失败: {e}")
            return True
