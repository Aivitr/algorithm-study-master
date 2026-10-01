import time, uuid, base64, hmac, hashlib, requests, re, os, json
from app.core import config  # 先加载 .env，确保 os.getenv 能读到阿里云密钥
import urllib.parse
import urllib3
import websocket
import threading

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# === 阿里云 NLS 配置 ===
ALIYUN_CONFIG = {
    'ACCESS_KEY_ID': os.getenv("ALIYUN_ACCESS_KEY_ID", ""),
    'ACCESS_KEY_SECRET': os.getenv("ALIYUN_ACCESS_KEY_SECRET", ""),
    'APP_KEY': os.getenv("ALIYUN_APP_KEY", "")
}

# === 共享 Token 管理 ===
_shared_token = None
_shared_token_expire = 0
_token_lock = threading.Lock()


def refresh_aliyun_token():
    """刷新阿里云 NLS Token（模块级共享，线程安全）"""
    global _shared_token, _shared_token_expire
    with _token_lock:
        if _shared_token and time.time() < _shared_token_expire - 60:
            return _shared_token
        try:
            client_id = ALIYUN_CONFIG['ACCESS_KEY_ID']
            client_secret = ALIYUN_CONFIG['ACCESS_KEY_SECRET']
            params = {
                "Action": "CreateToken",
                "Format": "JSON",
                "Version": "2019-02-28",
                "AccessKeyId": client_id,
                "SignatureMethod": "HMAC-SHA1",
                "SignatureVersion": "1.0",
                "SignatureNonce": str(uuid.uuid4()),
                "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
            sorted_params = sorted(params.items())
            qs = "&".join([f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}" for k, v in sorted_params])
            string_to_sign = 'GET&%2F&' + urllib.parse.quote(qs, safe='')
            key = client_secret + '&'
            sign = base64.b64encode(hmac.new(key.encode(), string_to_sign.encode(), hashlib.sha1).digest()).decode()
            params['Signature'] = sign

            resp = requests.get("https://nls-meta.cn-shanghai.aliyuncs.com/", params=params, timeout=5, verify=False)
            d = resp.json()
            if 'Token' in d:
                _shared_token = d['Token']['Id']
                _shared_token_expire = d['Token']['ExpireTime']
                print("[OK] 阿里云Token刷新成功")
                return _shared_token
            # 失败分支：接口返回 4xx 且不带 Token 字段时，记录响应码与消息。
            else:
                code = d.get("Code") if isinstance(d, dict) else None
                message = d.get("Message") if isinstance(d, dict) else None
                print(
                    "[ERROR] 阿里云Token接口未返回Token："
                    f"HTTP={resp.status_code} Code={code or '?'} Message={message or '?'}"
                )
        except Exception as e:
            print(f"[ERROR] Token刷新失败: {e}")
        return _shared_token


class AIEngine:
    def __init__(self):
        self.aliyun_token = None
        self.token_expire = 0

    def _refresh_token(self):
        """使用共享 Token"""
        token = refresh_aliyun_token()
        if token:
            self.aliyun_token = token
        return self.aliyun_token

    def transcribe_audio(self, audio_path):
        self._refresh_token()
        if not self.aliyun_token:
            print("[ERROR] Token不可用")
            return None

        ws_url = f"wss://nls-gateway.cn-shanghai.aliyuncs.com/ws/v1?token={self.aliyun_token}"
        result_text = []
        is_complete = threading.Event()
        task_started = threading.Event()
        task_id = str(uuid.uuid4()).replace('-', '')

        def on_message(ws, message):
            try:
                msg = json.loads(message)
                msg_name = msg.get('header', {}).get('name')

                if msg_name == 'TaskStarted' or msg_name == 'TranscriptionStarted':
                    task_started.set()
                elif msg_name == 'SentenceEnd':
                    text = msg.get('payload', {}).get('result')
                    if text:
                        result_text.append(text)
                elif msg_name == 'TranscriptionCompleted':
                    is_complete.set()
            except Exception as e:
                print(f"[DEBUG] Message parse error: {e}", flush=True)

        def on_error(ws, error):
            print(f"[DEBUG] WebSocket error: {error}", flush=True)
            is_complete.set()

        def on_close(ws, close_status, close_msg):
            is_complete.set()

        def on_open(ws):
            def send_audio():
                try:
                    start_msg = {
                        "header": {
                            "message_id": str(uuid.uuid4()).replace('-', ''),
                            "task_id": task_id,
                            "namespace": "SpeechTranscriber",
                            "name": "StartTranscription",
                            "appkey": ALIYUN_CONFIG['APP_KEY']
                        },
                        "payload": {
                            "format": "pcm",
                            "sample_rate": 16000,
                            "enable_intermediate_result": False,
                            "enable_punctuation_prediction": True,
                            "enable_inverse_text_normalization": True
                        }
                    }
                    ws.send(json.dumps(start_msg))

                    if not task_started.wait(timeout=5):
                        print("[DEBUG] Timeout waiting for TaskStarted", flush=True)
                        is_complete.set()
                        return

                    with open(audio_path, 'rb') as f:
                        audio_data = f.read()

                    chunk_size = 3200
                    for i in range(0, len(audio_data), chunk_size):
                        chunk = audio_data[i:i+chunk_size]
                        ws.send(chunk, opcode=websocket.ABNF.OPCODE_BINARY)
                        time.sleep(0.01)

                    stop_msg = {
                        "header": {
                            "message_id": str(uuid.uuid4()).replace('-', ''),
                            "task_id": task_id,
                            "namespace": "SpeechTranscriber",
                            "name": "StopTranscription",
                            "appkey": ALIYUN_CONFIG['APP_KEY']
                        }
                    }
                    ws.send(json.dumps(stop_msg))
                except Exception as e:
                    print(f"[DEBUG] send_audio error: {e}", flush=True)
                    is_complete.set()

            threading.Thread(target=send_audio, daemon=True).start()

        try:
            ws = websocket.WebSocketApp(
                ws_url,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close
            )

            ws_thread = threading.Thread(target=ws.run_forever)
            ws_thread.daemon = True
            ws_thread.start()

            is_complete.wait(timeout=20)
            ws.close()

            final_result = ''.join(result_text) if result_text else None
            if final_result:
                print(f"[OK] 识别结果: {final_result}")
            return final_result
        except Exception as e:
            print(f"[ERROR] 语音识别失败: {e}")
            return None


# === 实时语音转写器（流式，支持中间结果） ===
class RealtimeTranscriber:
    """
    持久的阿里云 NLS SpeechTranscriber WebSocket 连接。
    音频 PCM 数据通过 feed_audio() 持续输入，中间/最终结果通过回调返回。

    生命周期: start() → feed_audio(chunk) ... → stop()
    """

    def __init__(self, on_partial=None, on_final=None, on_error=None, enable_speaker_diarization=False, username=None):
        """
        on_partial(text, payload=None) - TranscriptionResultChanged 中间结果回调
        on_final(text, payload=None)   - SentenceEnd 最终结果回调
        on_error(msg)    - 错误回调
        enable_speaker_diarization - 是否启用说话人分离
        username - 用户名（用于说话人绑定）
        """
        self.on_partial = on_partial or (lambda text: None)
        self.on_final = on_final or (lambda text: None)
        self.on_error = on_error or (lambda msg: print(f"[ASR Error] {msg}"))

        self.ws = None
        self.task_id = None
        self.is_started = False
        self._task_started = threading.Event()

        # 说话人分离相关
        self.enable_speaker_diarization = enable_speaker_diarization
        self.username = username
        self.bound_speaker_id = None  # 绑定的说话人 ID
        self.speaker_binding_confirmed = False

    def start(self):
        """
        连接阿里云 NLS 并发送 StartTranscription。
        非阻塞 — WebSocket 在守护线程中运行。
        返回 True/False 表示是否启动成功。
        """
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
                    # 中间结果 — 实时显示的关键
                    payload = msg.get('payload', {})
                    text = payload.get('result', '')
                    if text:
                        if self.enable_speaker_diarization:
                            print(f"[DEBUG] 中间结果 payload: {json.dumps(payload, ensure_ascii=False)}")
                        self._emit_callback(self.on_partial, text, payload)

                elif name == 'SentenceEnd':
                    # 最终结果
                    payload = msg.get('payload', {})
                    text = payload.get('result', '')
                    if text:
                        if self.enable_speaker_diarization:
                            print(f"[DEBUG] 最终结果 payload: {json.dumps(payload, ensure_ascii=False)}")
                        self._emit_callback(self.on_final, text, payload)

                elif name == 'TranscriptionCompleted':
                    pass  # StopTranscription 后的正常完成

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
                    "max_sentence_silence": 800
                }
            }

            # ⭐ 如果启用说话人分离，添加参数
            if self.enable_speaker_diarization:
                # 尝试多个可能的参数名（阿里云文档不明确）
                start_msg["payload"]["enable_speaker_diarization"] = True
                start_msg["payload"]["enable_voice_detection"] = True
                print(f"[ASR] 已启用说话人分离功能 (用户: {self.username})")
                print(f"[DEBUG] 发送参数: {json.dumps(start_msg['payload'], ensure_ascii=False)}")

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

        # 等待 TaskStarted 确认
        if not self._task_started.wait(timeout=5):
            self.on_error("等待TaskStarted超时")
            return False

        self.is_started = True
        print(f"[ASR] 实时转写会话已启动 (task_id={self.task_id[:8]}...)")
        return True

    def feed_audio(self, pcm_chunk: bytes):
        """
        输入原始 PCM 音频数据。
        pcm_chunk: 16kHz 16-bit 单声道 PCM 字节数据
        """
        if self.is_started and self.ws:
            try:
                self.ws.send(pcm_chunk, opcode=websocket.ABNF.OPCODE_BINARY)
            except Exception as e:
                self.on_error(f"feed_audio错误: {e}")

    def stop(self):
        """发送 StopTranscription 并关闭连接"""
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

    def _emit_callback(self, callback, text, payload):
        """兼容旧的一参回调，同时把阿里云 payload 透传给新链路。"""
        try:
            callback(text, payload)
        except TypeError:
            callback(text)

    def _should_process_result(self, msg):
        """
        兼容旧接口：不在转写器里过滤 speaker_id。

        speaker_id -> 系统用户 ID 的映射交给 server.py 的 ASRSessionManager
        结合本地声纹完成。

        阿里云返回格式：
        {
            "payload": {
                "result": "识别的文本",
                "speaker_id": "spk0"  # 说话人 ID
            }
        }
        """
        payload = msg.get('payload', {})
        speaker_id = payload.get('speaker_id', None)

        return True


engine = AIEngine()
