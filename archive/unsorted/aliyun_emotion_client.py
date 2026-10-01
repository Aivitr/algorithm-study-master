import os
from app.core import config  # 先加载 .env，确保 os.getenv 能读到 facebody 密钥
from typing import Tuple

from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_facebody20191230.client import Client as FacebodyClient
from alibabacloud_facebody20191230 import models as facebody_models


ACCESS_KEY_ID = os.getenv("ALIYUN_FACE_ACCESS_KEY_ID", "")
ACCESS_KEY_SECRET = os.getenv("ALIYUN_FACE_ACCESS_KEY_SECRET", "")
ENDPOINT = "facebody.cn-shanghai.aliyuncs.com"


def _create_client() -> FacebodyClient:
    config = open_api_models.Config(
        access_key_id=ACCESS_KEY_ID,
        access_key_secret=ACCESS_KEY_SECRET,
    )
    config.endpoint = ENDPOINT
    return FacebodyClient(config)


class AliyunEmotionClient:
    def __init__(self):
        self.client = _create_client()
        self.last_call_ts = 0
        self.min_interval = 3.0

    def recognize_expression_by_url(self, image_url: str) -> Tuple[str, float]:
        now = float(__import__("time").time())
        if now - self.last_call_ts < self.min_interval:
            return "neutral", 0.5
        self.last_call_ts = now

        try:
            print(f"[AliyunEmotion] call url={image_url}")
            req = facebody_models.RecognizeExpressionRequest(
                image_url=image_url
            )
            resp = self.client.recognize_expression(req)

            raw_map = resp.body.to_map()
            print("[AliyunEmotion] raw response:", raw_map)

            data = raw_map.get("Data") or raw_map.get("data") or {}
            elements = data.get("Elements") or data.get("elements") or []
            if not elements:
                return "neutral", 0.5

            elem = elements[0]
            raw_label = elem.get("Expression", "neutral")
            prob = float(elem.get("FaceProbability", 0.5))

            mapping = {
                "happiness": "happy",
                "happy": "happy",
                "neutral": "neutral",
                "sadness": "sad",
                "sad": "sad",
                "anger": "angry",
                "surprise": "surprised",
            }
            label = mapping.get(str(raw_label).lower(), "neutral")
            return label, prob
        except Exception as e:
            print(f"[AliyunEmotion] 调用失败: {e}")
            return "neutral", 0.5
