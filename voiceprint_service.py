"""
轻量级声纹识别服务
用于在多人环境中精准识别单个用户的声音
"""
import os
import numpy as np
import wave
from typing import Optional, Dict, List
import pickle
from pathlib import Path

# 使用 speechbrain 的预训练声纹模型（轻量级）
try:
    from speechbrain.pretrained import EncoderClassifier
    VOICEPRINT_AVAILABLE = True
except ImportError:
    VOICEPRINT_AVAILABLE = False
    print("[WARN] speechbrain 未安装，声纹识别功能不可用")
    print("安装命令: pip install speechbrain")


class VoiceprintService:
    """声纹识别服务"""

    def __init__(self, storage_dir: str = "storage/voiceprints"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.model = None
        self.user_embeddings: Dict[str, np.ndarray] = {}
        self._load_model()
        self._load_user_embeddings()

    def _load_model(self):
        """加载声纹识别模型"""
        if not VOICEPRINT_AVAILABLE:
            return

        try:
            # 使用 ECAPA-TDNN 模型（轻量级，效果好）
            self.model = EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                savedir="storage/voiceprint_models"
            )
            print("[OK] 声纹识别模型加载成功")
        except Exception as e:
            print(f"[ERROR] 声纹模型加载失败: {e}")
            self.model = None

    def _load_user_embeddings(self):
        """加载已注册用户的声纹特征"""
        embeddings_file = self.storage_dir / "user_embeddings.pkl"
        if embeddings_file.exists():
            try:
                with open(embeddings_file, 'rb') as f:
                    self.user_embeddings = pickle.load(f)
                print(f"[OK] 加载 {len(self.user_embeddings)} 个用户声纹")
            except Exception as e:
                print(f"[ERROR] 加载声纹数据失败: {e}")

    def _save_user_embeddings(self):
        """保存用户声纹特征"""
        embeddings_file = self.storage_dir / "user_embeddings.pkl"
        try:
            with open(embeddings_file, 'wb') as f:
                pickle.dump(self.user_embeddings, f)
            print("[OK] 声纹数据已保存")
        except Exception as e:
            print(f"[ERROR] 保存声纹数据失败: {e}")

    def extract_embedding(self, audio_path: str) -> Optional[np.ndarray]:
        """从音频文件提取声纹特征向量"""
        if not self.model:
            return None

        try:
            # 提取声纹特征
            embedding = self.model.encode_batch(audio_path)
            return embedding.squeeze().cpu().numpy()
        except Exception as e:
            print(f"[ERROR] 提取声纹特征失败: {e}")
            return None

    def register_user(self, username: str, audio_path: str) -> bool:
        """
        注册用户声纹

        Args:
            username: 用户名
            audio_path: 用户语音样本路径（建议3-5秒清晰语音）

        Returns:
            是否注册成功
        """
        if not self.model:
            print("[ERROR] 声纹模型未加载")
            return False

        embedding = self.extract_embedding(audio_path)
        if embedding is None:
            return False

        self.user_embeddings[username] = embedding
        self._save_user_embeddings()
        print(f"[OK] 用户 {username} 声纹注册成功")
        return True

    def verify_speaker(self, username: str, audio_path: str, threshold: float = 0.25) -> Dict:
        """
        验证音频是否为指定用户说话

        Args:
            username: 用户名
            audio_path: 待验证的音频路径
            threshold: 相似度阈值（越小越严格，建议 0.2-0.3）

        Returns:
            {
                "is_match": bool,  # 是否匹配
                "confidence": float,  # 置信度 (0-1)
                "distance": float  # 特征距离
            }
        """
        if not self.model:
            return {"is_match": True, "confidence": 1.0, "distance": 0.0, "note": "声纹验证未启用"}

        if username not in self.user_embeddings:
            return {"is_match": True, "confidence": 1.0, "distance": 0.0, "note": "用户未注册声纹"}

        # 提取当前音频的声纹特征
        current_embedding = self.extract_embedding(audio_path)
        if current_embedding is None:
            return {"is_match": False, "confidence": 0.0, "distance": 999.0, "note": "特征提取失败"}

        # 计算与注册声纹的距离
        registered_embedding = self.user_embeddings[username]
        distance = np.linalg.norm(current_embedding - registered_embedding)

        # 转换为相似度（0-1）
        confidence = max(0.0, 1.0 - distance)
        is_match = distance < threshold

        return {
            "is_match": is_match,
            "confidence": round(confidence, 3),
            "distance": round(distance, 3)
        }

    def identify_speaker(self, audio_path: str, top_k: int = 3) -> List[Dict]:
        """
        识别音频中的说话人（从所有注册用户中匹配）

        Args:
            audio_path: 音频路径
            top_k: 返回前 k 个最匹配的用户

        Returns:
            [{"username": str, "confidence": float, "distance": float}, ...]
        """
        if not self.model or not self.user_embeddings:
            return []

        current_embedding = self.extract_embedding(audio_path)
        if current_embedding is None:
            return []

        # 计算与所有注册用户的距离
        results = []
        for username, registered_embedding in self.user_embeddings.items():
            distance = np.linalg.norm(current_embedding - registered_embedding)
            confidence = max(0.0, 1.0 - distance)
            results.append({
                "username": username,
                "confidence": round(confidence, 3),
                "distance": round(distance, 3)
            })

        # 按距离排序，返回最匹配的 top_k 个
        results.sort(key=lambda x: x["distance"])
        return results[:top_k]

    def is_user_registered(self, username: str) -> bool:
        """检查用户是否已注册声纹"""
        return username in self.user_embeddings

    def unregister_user(self, username: str) -> bool:
        """删除用户声纹"""
        if username in self.user_embeddings:
            del self.user_embeddings[username]
            self._save_user_embeddings()
            print(f"[OK] 用户 {username} 声纹已删除")
            return True
        return False


# 全局实例
voiceprint_service = VoiceprintService()


def filter_audio_by_voiceprint(audio_path: str, username: str, threshold: float = 0.25) -> bool:
    """
    过滤音频：判断是否为指定用户说话

    Args:
        audio_path: 音频文件路径
        username: 用户名
        threshold: 匹配阈值

    Returns:
        True 表示是该用户说话，False 表示不是
    """
    result = voiceprint_service.verify_speaker(username, audio_path, threshold)
    return result.get("is_match", True)
