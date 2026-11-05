"""
中文文本处理（负责人：岳柔；ASR 去重策略修复：陈虹宇）。

v0.2 能力：
- normalize_text      基础清洗（全角空格、空白压缩）+ ASR 噪声标记清洗；
                      可选开启 ASR 重复消重（默认关闭）
- tokenize            分词（有 jieba 用 jieba，没装降级按空白切）；
                      支持开关过滤口语填充词
- dedup_asr_repeats   ASR 专用重复消重，只处理能可靠判断为口吃/卡壳的重复

注意：引擎目前计算 LSA 和词数用的是 core/lsa/preprocessing.py
的旧分词（与旧实验基线一致）。等这里的中文分词方案定下来并
验证通过后，再把引擎切过来 —— 切换时要重新核对基线结果。
"""

import re

# ASR 口语填充词/语气词（在岳柔扩充版基础上保留）
_FILLER_WORDS = {
    "嗯", "啊", "呃", "噢", "哦", "哎呀", "哎",
    "那个", "就是", "就是说", "然后", "所以", "其实",
    "对吧", "是不是", "你知道", "呃对", "算了", "嗯对",
}


def dedup_asr_repeats(text: str) -> str:
    """ASR 重复片段消重（保守策略：宁可漏删，不可误删）。

    只处理能可靠判断为 ASR 口吃/卡壳的重复：

    - 英文/数字/空白分隔的词连续重复 3 次及以上 → 保留 1 个
      （"hello hello hello" → "hello"；"hello hello" 保留）
    - 同一两字词组连续重复 3 次及以上 → 收缩为 2 组
      （"好的好的好的好的" → "好的好的"；"讨论讨论"、"非常非常"
      只有 2 组，无法与正常表达区分，保留）
    - 同一汉字连续重复 3 次及以上 → 收缩为 2 个
      （"哈哈哈哈" → "哈哈"；"妈妈"、"天天" 只有 2 连，保留）

    明确不处理：
    - 只重复 2 次的两字词组（ABAB 是合法表达）
    - 带标点分隔的重复（如 "谢谢！谢谢！"）

    循环迭代直到文本不再变化，处理长重复串。
    """
    if not isinstance(text, str) or not text:
        return ""
    prev = None
    curr = text
    while prev != curr:
        prev = curr
        # 英文/数字整块重复：单词边界防止破坏 hello 内部的 ll；至少 3 次才收敛
        curr = re.sub(r"\b(\w+)\b(?:\s+\1\b){2,}", r"\1", curr)
        # 中文：先处理两字词组，再处理单字（顺序不能换，否则"谢谢谢谢"会被单字规则先吃掉）
        curr = re.sub(r"([一-鿿]{2})\1{2,}", r"\1\1", curr)
        curr = re.sub(r"([一-鿿])\1{2,}", r"\1\1", curr)
    return curr


def normalize_text(text: str | None, dedup: bool = False) -> str:
    """基础清洗：全角空格转半角、压缩连续空白、去首尾空白，
    并清除 ASR 常见噪声标记（[spk1]、[噪音]、[静音]、<unk>）。

    dedup=True 时额外调用 dedup_asr_repeats 做重复消重。
    默认关闭：保持课堂原始文本、LSA 输入与 GCA 指标与旧基线一致，
    ASR 场景由调用方显式开启。

    None 返回 ""；其他非字符串按 str() 强转（保持旧契约）。
    """
    if text is None:
        return ""
    t = str(text)
    # 清洗 ASR 常见标记噪声（对普通文本无影响）
    t = re.sub(r"\[spk\d+\]", " ", t)
    t = re.sub(r"\[噪音\]|\[静音\]|<unk>", " ", t)
    # 全角空格转半角 + 合并空白
    t = re.sub(r"[　]", " ", t)
    t = re.sub(r"\s+", " ", t)
    t = t.strip()
    if dedup:
        t = dedup_asr_repeats(t)
    return t


def tokenize(
    text: str | None,
    remove_filler: bool = True,
    dedup: bool = False,
) -> list[str]:
    """中文分词。

    - 有 jieba 用 jieba，没装降级按空白切（临时方案）；
    - remove_filler：过滤口语填充词，默认开启；
    - dedup：透传给 normalize_text 的 ASR 去重开关，默认关闭。
    """
    cleaned = normalize_text(text, dedup=dedup)
    if not cleaned:
        return []
    try:
        import jieba
        words = [w for w in jieba.cut(cleaned) if w.strip()]
    except ImportError:
        # jieba 不可用时降级：按空格切，中文句子会变成一整个词
        words = [w for w in cleaned.split(" ") if w.strip()]
    if remove_filler:
        words = [w for w in words if w not in _FILLER_WORDS]
    return words
