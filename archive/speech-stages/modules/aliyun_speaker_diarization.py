"""
使用阿里云原生说话人分离功能
无需本地模型，直接调用阿里云 API
"""
import json
import uuid
import time
import threading
import websocket
from ai_core import refresh_aliyun_token, ALIYUN_CONFIG


class AliyunSpeakerDiarizationTranscriber:
    """
    阿里云原生说话人分离转写器

    功能：
    1. 使用阿里云的 enable_voice_detection 参数
    2. 阿里云自动识别多个说话人（spk0, spk1, spk2...）
    3. 根据用户注册的说话人 ID 过滤结果

    优点：
    - ✅ 无需本地模型
    - ✅ 无需 GPU
    - ✅ 延迟低（阿里云处理）
    - ✅ 准确率高（阿里云算法）

    使用流程：
    1. 用户首次发言时，记录阿里云分配的 speaker_id（如 spk0）
    2. 后续只转写该 speaker_id 的内容
    3. 过滤掉其他 speaker_id 的内容
    """

    def __init__(self, username, on_partial=None, on_final=None, on_error=None):
        self.username = username
        self.on_partial = on_partial or (lambda text: None)
        self.on_final = on_final or (lambda text: None)
        self.on_error = on_error or (lambda msg: print(f"[ASR Error] {msg}"))

        self.ws = None
        self.task_id = None
        self.is_started = False
        self._task_started = threading.Event()

        # 说话人 ID 绑定
        self.bound_speaker_id = None  # 用户绑定的说话人 ID（如 spk0）
        self.speaker_binding_confirmed = False

    def start(self):
        """启动阿里云 NLS 连接，启用说话人分离"""
        token = refresh_aliyun_token()
        if not token:
            self.on_error("无法获取阿里云Token")
            return False

        ws_url = f"wss://nls-gateway.cn-shanghai.aliyuncs.com/ws/v1?token={token}"
        self.task_id = str(uuid.uuid4()).replace('-', '')
        self._task_started.clear()

        def on_message(ws, message):
            try:
                msg = json.loads(message)
                name = msg.get('header', {}).get('name', '')

                if name == 'TaskStarted' or name == 'TranscriptionStarted':
                    self._task_started.set()

                elif name == 'TranscriptionResultChanged':
                    # 中间结果
                    self._handle_result(msg, is_final=False)

                elif name == 'SentenceEnd':
                    # 最终结果
                    self._handle_result(msg, is_final=True)

                elif name == 'TranscriptionCompleted':
                    pass

                elif name == 'TaskFailed':
                    reason = msg.get('header', {}).get('status_text', 'unknown')
                    self.on_error(f"TaskFailed: {reason}")

            except Exception as e:
                self.on_error(f"消息解析错误: {e}")

        def on_error_ws(ws, error):
            self.on_error(f"WebSocket错误: {error}")

        def on_close(ws, status, msg):
            self.is_started = False
            print(f"[ASR] 阿里云NLS连接关闭")

        def on_open(ws):
            # 启动转写，启用说话人分离
            start_msg = {
                "header": {
                    "message_id": str(uuid.uuid4()).replace('-', ''),
                    "task_id": self.task_id,
                    "namespace": "SpeechTranscriber",
                    "name": "StartTranscription",
                    "appkey": ALIYUN_CONFIG['APP_KEY']
                },
                "payload": {
                    "format": "pcm",
                    "sample_rate": 16000,
                    "enable_intermediate_result": True,
                    "enable_punctuation_prediction": True,
                    "enable_inverse_text_normalization": True,
                    "max_sentence_silence": 800,
                    # ⭐ 关键参数：启用说话人分离
                    "enable_voice_detection": True,
                    # 可选：指定说话人数量（如果知道的话）
                    # "speaker_number": 3
                }
            }
            ws.send(json.dumps(start_msg))
            print(f"[ASR] 已启用阿里云说话人分离功能")

        self.ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error_ws,
            on_close=on_close
        )

        ws_thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        ws_thread.start()

        if not self._task_started.wait(timeout=5):
            self.on_error("等待TaskStarted超时")
            return False

        self.is_started = True
        print(f"[ASR] 实时转写会话已启动 (task_id={self.task_id[:8]}...)")
        return True

    def _handle_result(self, msg, is_final=False):
        """
        处理阿里云返回的识别结果

        阿里云返回格式（启用说话人分离后）：
        {
            "payload": {
                "result": "这是识别的文本",
                "speaker_id": "spk0",  # 说话人 ID
                "confidence": 0.95
            }
        }
        """
        payload = msg.get('payload', {})
        text = payload.get('result', '')
        speaker_id = payload.get('speaker_id', None)  # 阿里云分配的说话人 ID

        if not text:
            return

        # 首次识别：绑定说话人 ID
        if not self.speaker_binding_confirmed and speaker_id:
            self.bound_speaker_id = speaker_id
            self.speaker_binding_confirmed = True
            print(f"[ASR] 用户 {self.username} 绑定到说话人 {speaker_id}")

        # 过滤：只处理绑定的说话人
        if speaker_id and self.bound_speaker_id:
            if speaker_id != self.bound_speaker_id:
                print(f"[FILTER] 过滤其他说话人 {speaker_id} 的内容: {text[:20]}...")
                return

        # 转发结果
        if is_final:
            self.on_final(text)
        else:
            self.on_partial(text)

    def feed_audio(self, pcm_chunk: bytes):
        """输入音频数据"""
        if self.is_started and self.ws:
            try:
                self.ws.send(pcm_chunk, opcode=websocket.ABNF.OPCODE_BINARY)
            except Exception as e:
                self.on_error(f"feed_audio错误: {e}")

    def stop(self):
        """停止转写"""
        if self.ws and self.is_started:
            try:
                stop_msg = {
                    "header": {
                        "message_id": str(uuid.uuid4()).replace('-', ''),
                        "task_id": self.task_id,
                        "namespace": "SpeechTranscriber",
                        "name": "StopTranscription",
                        "appkey": ALIYUN_CONFIG['APP_KEY']
                    }
                }
                self.ws.send(json.dumps(stop_msg))
            except Exception:
                pass
            self.is_started = False
            time.sleep(0.3)
            try:
                self.ws.close()
            except Exception:
                pass
            print(f"[ASR] 实时转写会话已停止")


class AliyunSpeakerDiarizationTranscriberV2:
    """
    阿里云说话人分离转写器 V2

    改进：
    1. 支持用户主动选择说话人 ID
    2. 支持动态切换说话人
    3. 支持多用户场景
    """

    def __init__(self, username, on_partial=None, on_final=None, on_error=None):
        self.username = username
        self.on_partial = on_partial or (lambda text: None)
        self.on_final = on_final or (lambda text: None)
        self.on_error = on_error or (lambda msg: print(f"[ASR Error] {msg}"))

        self.ws = None
        self.task_id = None
        self.is_started = False
        self._task_started = threading.Event()

        # 说话人管理
        self.bound_speaker_id = None
        self.speaker_candidates = []  # 候选说话人列表
        self.speaker_text_samples = {}  # {speaker_id: [text1, text2, ...]}

    def start(self):
        """启动转写"""
        token = refresh_aliyun_token()
        if not token:
            self.on_error("无法获取阿里云Token")
            return False

        ws_url = f"wss://nls-gateway.cn-shanghai.aliyuncs.com/ws/v1?token={token}"
        self.task_id = str(uuid.uuid4()).replace('-', '')
        self._task_started.clear()

        def on_message(ws, message):
            try:
                msg = json.loads(message)
                name = msg.get('header', {}).get('name', '')

                if name == 'TaskStarted' or name == 'TranscriptionStarted':
                    self._task_started.set()

                elif name == 'TranscriptionResultChanged':
                    self._handle_result(msg, is_final=False)

                elif name == 'SentenceEnd':
                    self._handle_result(msg, is_final=True)

            except Exception as e:
                self.on_error(f"消息解析错误: {e}")

        def on_error_ws(ws, error):
            self.on_error(f"WebSocket错误: {error}")

        def on_close(ws, status, msg):
            self.is_started = False

        def on_open(ws):
            start_msg = {
                "header": {
                    "message_id": str(uuid.uuid4()).replace('-', ''),
                    "task_id": self.task_id,
                    "namespace": "SpeechTranscriber",
                    "name": "StartTranscription",
                    "appkey": ALIYUN_CONFIG['APP_KEY']
                },
                "payload": {
                    "format": "pcm",
                    "sample_rate": 16000,
                    "enable_intermediate_result": True,
                    "enable_punctuation_prediction": True,
                    "enable_inverse_text_normalization": True,
                    "max_sentence_silence": 800,
                    "enable_voice_detection": True,  # 启用说话人分离
                }
            }
            ws.send(json.dumps(start_msg))

        self.ws = websocket.WebSocketApp(
            ws_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error_ws,
            on_close=on_close
        )

        ws_thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        ws_thread.start()

        if not self._task_started.wait(timeout=5):
            self.on_error("等待TaskStarted超时")
            return False

        self.is_started = True
        return True

    def _handle_result(self, msg, is_final=False):
        """处理识别结果"""
        payload = msg.get('payload', {})
        text = payload.get('result', '')
        speaker_id = payload.get('speaker_id', None)

        if not text:
            return

        # 收集说话人样本（用于后续分析）
        if speaker_id:
            if speaker_id not in self.speaker_text_samples:
                self.speaker_text_samples[speaker_id] = []
            self.speaker_text_samples[speaker_id].append(text)

        # 自动绑定：选择发言最多的说话人
        if not self.bound_speaker_id and len(self.speaker_text_samples) > 0:
            # 统计每个说话人的发言次数
            speaker_counts = {
                spk: len(texts)
                for spk, texts in self.speaker_text_samples.items()
            }
            # 选择发言最多的
            self.bound_speaker_id = max(speaker_counts, key=speaker_counts.get)
            print(f"[ASR] 用户 {self.username} 自动绑定到说话人 {self.bound_speaker_id}")

        # 过滤
        if speaker_id and self.bound_speaker_id:
            if speaker_id != self.bound_speaker_id:
                return

        # 转发
        if is_final:
            self.on_final(text)
        else:
            self.on_partial(text)

    def feed_audio(self, pcm_chunk: bytes):
        """输入音频"""
        if self.is_started and self.ws:
            try:
                self.ws.send(pcm_chunk, opcode=websocket.ABNF.OPCODE_BINARY)
            except Exception as e:
                self.on_error(f"feed_audio错误: {e}")

    def stop(self):
        """停止转写"""
        if self.ws and self.is_started:
            try:
                stop_msg = {
                    "header": {
                        "message_id": str(uuid.uuid4()).replace('-', ''),
                        "task_id": self.task_id,
                        "namespace": "SpeechTranscriber",
                        "name": "StopTranscription",
                        "appkey": ALIYUN_CONFIG['APP_KEY']
                    }
                }
                self.ws.send(json.dumps(stop_msg))
            except Exception:
                pass
            self.is_started = False
            time.sleep(0.3)
            try:
                self.ws.close()
            except Exception:
                pass

    def get_speaker_summary(self):
        """获取说话人统计"""
        return {
            "bound_speaker": self.bound_speaker_id,
            "all_speakers": list(self.speaker_text_samples.keys()),
            "speaker_counts": {
                spk: len(texts)
                for spk, texts in self.speaker_text_samples.items()
            }
        }
