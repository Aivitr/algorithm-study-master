"""情绪标签归一化（阶段 5 从 server.py 迁出）。

把各家情绪识别来源（面部分析、LLM、前端上报）给出的五花八门的标签，
统一到一组固定的英文标签上。带别名词典，含中文别名。

判定它是"共享的"的依据：全仓库有 19 处调用它，横跨实时链路、报告生成、
情绪统计等多个域。它必须只有**一份**实现——两份迟早分叉，表现为
同一个表情在不同页面上被归成不同的类，且不报错。

`server.py` 用 `from app.core.emotions import normalize_emotion_label`
**再导出**，因此既有的 `normalize_emotion_label(...)` 调用点全部不变。

注意这里的 `import re` 是**必需的**：函数体用 `re.split` 拆复合标签。在
server.py 里它靠的是那边的模块级 `import re`，搬出来时必须自己带上——
少了它的后果不是导入失败，而是**运行到那条分支才 NameError**，且外层
处理器会把异常吞成 `{"status":"error"}` 的 200 响应（见
`tests_safe/test_module_free_names.py`）。
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
