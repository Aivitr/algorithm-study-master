"""
中文文本处理（负责人：岳柔）。

v0.1 只提供最基础的两个函数，保证流程能跑通：
    normalize_text  基础清洗（全角空格、多余空白）
    tokenize        分词（装了 jieba 用 jieba，没装先按空白切）

注意：引擎目前计算 LSA 和词数用的是 core/lsa/preprocessing.py
的旧分词（与旧实验基线一致）。等这里的中文分词方案定下来并
验证通过后，再把引擎切过来 —— 切换时要重新核对基线结果。

待办（岳柔）：
    - 确定中文分词方案（jieba / 其他）
    - 口语词过滤表
    - ASR 重复片段清理
    - 测试样例（tests/test_chinese_*.py）
"""

"""中文文本处理（负责人：岳柔）。

v0.1 基础版：保证流程能跑通，不追求完美分词。
"""

import re

_FULLWIDTH_SPACE_RE = re.compile(r"[　]")
_WHITESPACE_RE = re.compile(r"\s+")

# 极简口语词过滤（先写几个常见的，后面再扩）
_FILLER_WORDS = {"嗯", "啊", "呃", "那个", "就是说", "然后", "所以", "其实"}


def normalize_text(text: str | None) -> str:
    """基础清洗：全角空格转半角、压缩连续空白、去首尾空白。"""
    if text is None:
        return ""
    t = _FULLWIDTH_SPACE_RE.sub(" ", str(text))
    t = _WHITESPACE_RE.sub(" ", t)
    return t.strip()


def tokenize(text: str | None) -> list[str]:
    """中文分词（v0.1）。

    - 有 jieba 用 jieba
    - 没 jieba 按空白切（临时方案）
    - 顺手过滤掉极简口语词
    """
    cleaned = normalize_text(text)
    if not cleaned:
        return []

    try:
        import jieba
        words = [w for w in jieba.cut(cleaned) if w.strip()]
    except ImportError:
        words = [w for w in cleaned.split(" ") if w.strip()]

    return [w for w in words if w not in _FILLER_WORDS]