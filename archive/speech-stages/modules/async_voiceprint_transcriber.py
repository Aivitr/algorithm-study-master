"""
异步声纹验证方案 - 保持实时性
先转写，后验证，再修正
"""
import asyncio
import threading
from typing import Optional, Callable
from ai_core import RealtimeTranscriber


class AsyncVoiceprintTranscriber(RealtimeTranscriber):
    """
    异步声纹验证转写器

    工作流程：
    1. 音频直接发送到阿里云 ASR（保持实时性）
    2. 同时保存音频副本到缓冲区
    3. 异步进行声纹验证
    4. 如果验证失败，撤回已发送的转写结果

    优点：
    - 实时性不受影响（延迟仍是 200-500ms）
    - 用户体验好（立即看到转写结果）
    - 可选择性启用声纹验证

    缺点：
    - 可能出现"闪烁"（先显示后撤回）
    - 需要前端支持消息撤回
    """

    def __init__(
        self,
        username: str,
        on_partial: Optional[Callable] = None,
        on_final: Optional[Callable] = None,
        on_error: Optional[Callable] = None,
        enable_async_verification: bool = True
    ):
        # 包装回调函数，添加消息 ID
        self.username = username
        self.enable_async_verification = enable_async_verification
        self.message_counter = 0
        self.pending_verifications = {}  # {message_id: audio_data}

        # 原始回调
        self.original_on_partial = on_partial
        self.original_on_final = on_final

        # 包装后的回调
        def wrapped_on_partial(text):
            msg_id = self._generate_message_id()
            if on_partial:
                on_partial(text, msg_id)  # 传递消息 ID

        def wrapped_on_final(text):
            msg_id = self._generate_message_id()
            if on_final:
                on_final(text, msg_id)  # 传递消息 ID
            # 异步验证
            if self.enable_async_verification:
                self._schedule_verification(msg_id, text)

        super().__init__(wrapped_on_partial, wrapped_on_final, on_error)

        # 音频缓冲（用于异步验证）
        self.audio_buffer = []
        self.buffer_lock = threading.Lock()

    def _generate_message_id(self) -> str:
        """生成唯一消息 ID"""
        self.message_counter += 1
        return f"{self.username}_{self.message_counter}_{int(time.time() * 1000)}"

    def feed_audio(self, pcm_chunk: bytes):
        """
        输入音频 - 直接转发，同时保存副本
        """
        # 1. 直接转发到阿里云（保持实时性）
        super().feed_audio(pcm_chunk)

        # 2. 保存音频副本（用于异步验证）
        if self.enable_async_verification:
            with self.buffer_lock:
                self.audio_buffer.append(pcm_chunk)

    def _schedule_verification(self, message_id: str, text: str):
        """
        调度异步声纹验证
        """
        with self.buffer_lock:
            audio_data = b''.join(self.audio_buffer)
            self.audio_buffer.clear()

        # 在后台线程中验证
        threading.Thread(
            target=self._verify_and_callback,
            args=(message_id, text, audio_data),
            daemon=True
        ).start()

    def _verify_and_callback(self, message_id: str, text: str, audio_data: bytes):
        """
        后台验证声纹
        """
        try:
            # 这里可以用深度学习模型（不影响实时性）
            from voiceprint_service import voiceprint_service
            import tempfile
            import wave
            import os

            # 保存为临时文件
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp_path = tmp.name
                with wave.open(tmp_path, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(audio_data)

            # 验证声纹
            result = voiceprint_service.verify_speaker(self.username, tmp_path)
            os.unlink(tmp_path)

            # 如果验证失败，通知前端撤回消息
            if not result.get("is_match"):
                print(f"[ASYNC VERIFY] 检测到非目标用户，撤回消息: {message_id}")
                if self.on_error:
                    self.on_error({
                        "type": "revoke_message",
                        "message_id": message_id,
                        "reason": "非目标用户声音",
                        "confidence": result.get("confidence")
                    })

        except Exception as e:
            print(f"[ERROR] 异步验证失败: {e}")


# ============ 前端配合 ============

"""
前端需要支持消息撤回：

// JavaScript 示例
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    if (data.type === 'asr_final') {
        // 显示转写结果
        addMessage(data.message_id, data.username, data.text);
    }

    if (data.type === 'revoke_message') {
        // 撤回消息（异步验证失败）
        removeMessage(data.message_id);
        console.log('检测到非目标用户声音，已过滤');
    }
};
"""
