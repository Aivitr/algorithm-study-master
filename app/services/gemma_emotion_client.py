"""
Gemma 4 情绪识别客户端
通过 Ollama 本地部署的 Gemma 4 (gemma:4b) 进行面部情绪分析
"""

import requests
import time
import re
from typing import Tuple, Optional

# 有效的情绪标签
VALID_EMOTIONS = {"happy", "sad", "angry", "surprised", "neutral",
                  "excited", "confused", "thinking", "calm"}


class GemmaEmotionClient:
    """Gemma 4 情绪识别客户端"""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "gemma4:e4b"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.last_call_ts = 0
        self.min_interval = 1.0  # 最小调用间隔（秒）
        self.default_options = {
            "temperature": 0.1,
            "num_predict": 80,
            "num_ctx": 1024,
            "num_thread": 4
        }
        # 低内存回退参数：当 Ollama 报内存布局错误时使用
        self.low_memory_options = {
            "temperature": 0.1,
            "num_predict": 24,
            "num_ctx": 512,
            "num_thread": 2
        }
        self.chat_timeout = 12
        self.generate_timeout = 8
        self.cooldown_seconds = 20
        self.cooldown_until = 0.0
        self.consecutive_failures = 0
        self.max_failures_before_cooldown = 2

        # 情绪值映射（用于数值转换）
        self.emotion_values = {
            "excited": 95,
            "happy": 85,
            "surprised": 75,
            "thinking": 45,
            "confused": 35,
            "calm": 60,
            "neutral": 50,
            "sad": 25,
            "angry": 15
        }

    def _check_health(self) -> bool:
        """检查 Ollama 服务是否可用"""
        try:
            # 尝试多个端点
            for endpoint in ["/api/tags", "/api/version", "/"]:
                response = requests.get(f"{self.base_url}{endpoint}", timeout=5)
                if response.status_code == 200:
                    return True
            return False
        except Exception:
            return False

    def _call_ollama(self, prompt: str, timeout: int = 30) -> Optional[str]:
        """
        调用 Ollama API 生成文本

        Args:
            prompt: 输入提示词
            timeout: 超时时间（秒）

        Returns:
            模型生成的文本，或 None（失败时）
        """
        try:
            last_error_text = ""
            force_low_memory = False

            # 优先使用 /api/chat (新版 Ollama 推荐)
            try:
                response = requests.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "user", "content": prompt}
                        ],
                        "stream": False,
                        "think": False,  # 禁用 Gemma 的 thinking 模式
                        "keep_alive": "0s",
                        "options": self.default_options
                    },
                    timeout=min(timeout, self.chat_timeout)
                )

                if response.status_code == 200:
                    result = response.json()
                    # 优先从 content 获取，否则从 thinking 获取
                    content = result.get("message", {}).get("content", "")
                    if not content:
                        content = result.get("message", {}).get("thinking", "")
                    return content.strip()
                else:
                    last_error_text = response.text or ""
                    print(f"[GemmaEmotion] /api/chat 错误: {response.status_code} - {last_error_text}")
                    force_low_memory = "memory layout cannot be allocated" in last_error_text.lower()

            except requests.exceptions.Timeout:
                print(f"[GemmaEmotion] /api/chat 超时(>{self.chat_timeout}s)，尝试快速回退...")
                force_low_memory = True
            except Exception as e:
                print(f"[GemmaEmotion] /api/chat 失败: {e}")

            # 回退到 /api/generate (旧版 Ollama)
            use_low_memory = force_low_memory or "memory layout cannot be allocated" in last_error_text.lower()
            options = self.low_memory_options if use_low_memory else self.default_options
            if use_low_memory:
                print("[GemmaEmotion] 检测到内存不足，切换低内存参数重试...")

            response = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "keep_alive": "0s",
                    "options": options
                },
                timeout=min(timeout, self.generate_timeout)
            )

            if response.status_code == 200:
                return response.json().get("response", "").strip()
            else:
                print(f"[GemmaEmotion] API 错误: {response.status_code} - {response.text}")
                return None

        except requests.exceptions.Timeout:
            print("[GemmaEmotion] 调用超时")
            return None
        except Exception as e:
            print(f"[GemmaEmotion] 调用失败: {e}")
            return None

    def _features_to_description(self, features: dict) -> str:
        """
        将面部特征转换为描述文本

        Args:
            features: 包含以下键的字典:
                - mouth_open: 嘴巴张开程度 (0.0-1.0)
                - smile_lift: 微笑上扬程度 (-1.0 到 1.0)
                - brow_raise: 眉毛抬高程度 (0.0-1.0)
                - eye_open: 眼睛睁大程度 (0.0-1.0)

        Returns:
            描述文本
        """
        mouth = features.get("mouth_open", 0.0)
        smile = features.get("smile_lift", 0.0)
        brow = features.get("brow_raise", 0.0)
        eye = features.get("eye_open", 0.0)

        # 构造中文描述（适配 Gemma 的多语言能力）
        descriptions = []

        if smile > 0.3:
            descriptions.append("嘴角上扬，呈现微笑表情")
        elif smile < -0.3:
            descriptions.append("嘴角下垂，可能是不开心或悲伤")

        if mouth > 0.3:
            descriptions.append("嘴巴张开")
        elif mouth < 0.1:
            descriptions.append("嘴巴闭合")

        if brow > 0.3:
            descriptions.append("眉毛抬高")
        elif brow < -0.1:
            descriptions.append("眉毛下压，可能表示愤怒或专注")

        if eye > 0.5:
            descriptions.append("眼睛睁大")
        elif eye < 0.3:
            descriptions.append("眼睛微闭")

        if not descriptions:
            descriptions.append("面部表情平静")

        return "，".join(descriptions)

    def _parse_response(self, response: str) -> Tuple[Optional[str], float]:
        """
        解析 Gemma 的响应

        Args:
            response: Gemma 返回的原始文本

        Returns:
            (emotion, confidence) 元组
        """
        if not response:
            return None, 0.0

        # 尝试提取 emotion 和 confidence
        emotion = None
        confidence = 0.5

        # 匹配 "emotion: xxx" 或 "emotion:xxx"
        emotion_match = re.search(r"emotion[:\s]+(\w+)", response, re.IGNORECASE)
        if emotion_match:
            emotion = emotion_match.group(1).lower()

        # 匹配 "confidence: x.xx" 或 "confidence:xxx"
        conf_match = re.search(r"confidence[:\s]+([\d.]+)", response, re.IGNORECASE)
        if conf_match:
            try:
                confidence = float(conf_match.group(1))
            except ValueError:
                pass

        # 如果没有匹配到，尝试直接匹配情绪词
        if not emotion:
            for valid_emotion in VALID_EMOTIONS:
                if valid_emotion in response.lower():
                    emotion = valid_emotion
                    break

        # 验证情绪标签
        if emotion and emotion not in VALID_EMOTIONS:
            # 尝试映射相似标签
            mapping = {
                "happiness": "happy",
                "sadness": "sad",
                "anger": "angry",
                "surprise": "surprised",
                "fear": "confused",
                "disgust": "confused",
                "contempt": "confused",
                "relaxed": "calm",
                "neutrality": "neutral"
            }
            emotion = mapping.get(emotion, None)

        return emotion, confidence

    def analyze_emotion(self, features: dict) -> Tuple[str, float]:
        """
        分析面部情绪

        Args:
            features: 面部特征字典，包含:
                - mouth_open: 嘴巴张开程度 (0.0-1.0)
                - smile_lift: 微笑上扬程度 (-1.0 到 1.0)
                - brow_raise: 眉毛抬高程度 (0.0-1.0)
                - eye_open: 眼睛睁大程度 (0.0-1.0)

        Returns:
            (emotion, confidence) 元组
        """
        # 频率限制
        now = time.time()
        if now - self.last_call_ts < self.min_interval:
            return "neutral", 0.5
        self.last_call_ts = now

        # 熔断冷却：连续失败后暂时跳过 Gemma，避免每帧阻塞
        if now < self.cooldown_until:
            return "neutral", 0.5

        # 检查服务健康
        if not self._check_health():
            print("[GemmaEmotion] Ollama 服务不可用")
            return "neutral", 0.5

        # 生成描述
        normalized_features = {
            "mouth_open": float(features.get("mouth_open", 0.0)),
            "smile_lift": float(features.get("smile_lift", 0.0)),
            "brow_raise": float(features.get("brow_raise", 0.0)),
            "eye_open": float(features.get("eye_open", 0.0)),
        }

        description = self._features_to_description(normalized_features)

        # 构造提示词
        prompt = f"""你是一个面部情绪识别专家。根据以下面部特征描述，判断人物情绪。

面部特征: {description}
关键数值: mouth_open={normalized_features['mouth_open']:.3f}, smile_lift={normalized_features['smile_lift']:.3f}, brow_raise={normalized_features['brow_raise']:.3f}, eye_open={normalized_features['eye_open']:.3f}

可选情绪标签: happy, sad, angry, surprised, neutral, excited, confused, thinking, calm

请仅输出一个情绪标签和置信度，格式如下:
emotion: [情绪标签]
confidence: [0.0-1.0]

只输出这两行，不要其他内容。"""

        # 调用 Gemma
        response = self._call_ollama(prompt)

        if response:
            emotion, confidence = self._parse_response(response)
            if emotion:
                self.consecutive_failures = 0
                return emotion, confidence
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.max_failures_before_cooldown:
            self.cooldown_until = time.time() + self.cooldown_seconds
            self.consecutive_failures = 0
            print(f"[GemmaEmotion] 连续失败，进入 {self.cooldown_seconds}s 冷却")
        return "neutral", 0.5

    def analyze_with_image_base64(self, image_base64: str) -> Tuple[str, float]:
        """
        使用 Base64 编码的图片进行分析（备用方案）

        注意: Gemma 4b 的视觉能力有限，建议使用特征描述方式

        Args:
            image_base64: Base64 编码的图片数据

        Returns:
            (emotion, confidence) 元组
        """
        now = time.time()
        if now - self.last_call_ts < self.min_interval:
            return "neutral", 0.5
        self.last_call_ts = now

        if not self._check_health():
            return "neutral", 0.5

        prompt = f"""分析这张人脸图片中的情绪表情。

可选情绪标签: happy, sad, angry, surprised, neutral, excited, confused, thinking, calm

请输出:
emotion: [情绪标签]
confidence: [0.0-1.0]
"""

        try:
            # 使用 /api/chat
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "images": [image_base64],
                    "stream": False,
                    "think": False,  # 禁用 Gemma 的 thinking 模式
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 100
                    }
                },
                timeout=60
            )

            if response.status_code == 200:
                result = response.json()
                content = result.get("message", {}).get("content", "")
                if not content:
                    content = result.get("message", {}).get("thinking", "")
                content = content.strip()
                emotion, confidence = self._parse_response(content)
                if emotion:
                    return emotion, confidence

        except Exception as e:
            print(f"[GemmaEmotion] 图片分析失败: {e}")

        return "neutral", 0.5


# 单例模式，方便全局使用
_instance = None


def get_gemma_client() -> Optional[GemmaEmotionClient]:
    """获取全局 Gemma 客户端实例"""
    global _instance
    if _instance is None:
        try:
            _instance = GemmaEmotionClient()
            # 验证连接
            if not _instance._check_health():
                print("[GemmaEmotion] 警告: Ollama 服务不可用")
                return None
        except Exception as e:
            print(f"[GemmaEmotion] 初始化失败: {e}")
            return None
    return _instance
