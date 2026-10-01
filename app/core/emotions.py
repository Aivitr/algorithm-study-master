"""情绪标签归一化。

把各家情绪识别来源（面部分析、LLM、前端上报）给出的五花八门的标签，
统一到一组固定的英文标签上。带别名词典，含中文别名。
全仓库只有这一份实现——两份迟早分叉，表现为同一个表情在不同页面上被归成
不同的类。

注意这里的 `import re` 是**必需的**：函数体用 `re.split` 拆复合标签。
"""

import re


def normalize_emotion_label(label: str) -> str:
    raw = str(label or "").strip().lower()
    if not raw:
        return "neutral"
    raw = raw.split("|", 1)[0].strip()
    raw = raw.replace(" ", "_").replace("-", "_")

    aliases = {
        "happy": "happy",
        "happiness": "happy",
        "joy": "happy",
        "joyful": "happy",
        "smile": "happy",
        "smiling": "happy",
        "pleased": "happy",
        "delight": "happy",
        "positive": "happy",
        "\u5f00\u5fc3": "happy",
        "\u9ad8\u5174": "happy",
        "\u5feb\u4e50": "happy",
        "\u5fae\u7b11": "happy",
        "excited": "excited",
        "excite": "excited",
        "energetic": "excited",
        "active": "excited",
        "\u5174\u594b": "excited",
        "surprise": "surprised",
        "surprised": "surprised",
        "surprise/excited": "surprised",
        "\u60ca\u559c": "surprised",
        "\u60ca\u8bb6": "surprised",
        "calm": "calm",
        "relaxed": "calm",
        "relax": "calm",
        "peaceful": "calm",
        "\u5e73\u9759": "calm",
        "neutral": "neutral",
        "normal": "neutral",
        "thinking": "thinking",
        "thoughtful": "thinking",
        "focused": "thinking",
        "focus": "thinking",
        "\u601d\u8003": "thinking",
        "confused": "confused",
        "confusion": "confused",
        "uncertain": "confused",
        "fear": "confused",
        "fearful": "confused",
        "anxious": "confused",
        "worried": "confused",
        "nervous": "confused",
        "disgust": "confused",
        "contempt": "confused",
        "anxious/frown": "confused",
        "\u56f0\u60d1": "confused",
        "\u62c5\u5fc3": "confused",
        "sad": "sad",
        "sadness": "sad",
        "down": "sad",
        "unhappy": "sad",
        "\u96be\u8fc7": "sad",
        "angry": "angry",
        "anger": "angry",
        "mad": "angry",
        "\u751f\u6c14": "angry",
    }

    if raw in aliases:
        return aliases[raw]

    for part in re.split(r"[/,;]+", raw):
        part = part.strip()
        if part in aliases:
            return aliases[part]

    return raw or "neutral"
