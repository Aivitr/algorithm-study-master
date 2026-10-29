"""
中文文本处理（负责人：岳柔）。
v0.2 新增ASR后处理能力：重复片段去重、噪声标记清洗、口语填充词过滤。
注意：引擎目前计算 LSA 和词数用的是 core/lsa/preprocessing.py
的旧分词（与旧实验基线一致）。等这里的中文分词方案定下来并
验证通过后，再把引擎切过来 —— 切换时要重新核对基线结果。

函数说明：
    normalize_text  基础清洗：全角空格、多余空白；新增ASR标记清洗、连续重复片段去重
    tokenize        分词（装了 jieba 用 jieba，没装先按空白切）；支持开关过滤口语填充词
    dedup_asr_repeats ASR专用：消除中文/英文数字连续重复文本，循环迭代处理长重复串

"""
import re
import jieba
from typing import List, Optional


def dedup_asr_repeats(text: str) -> str:
    """ASR重复片段消重。
    循环迭代消除连续重复：中文单字、两字词组、英文/数字整块重复；
    循环直到文本不再变化，处理单次正则无法清理干净的长重复串。
    """
    if not isinstance(text, str) or not text:
        return ""
    # 循环消重，直到没有变化，解决长重复串一次处理不干净
    prev = None
    curr = text
    while prev != curr:
        prev = curr
        # 修复：英文/数字【整块单词重复】，加单词边界，不会破坏hello内部ll
        # 匹配："hello hello" 这种空格隔开重复单词，不会匹配hello里面的ll
        curr = re.sub(r'\b(\w+)\b(?:\s+\1\b)+', r'\1', curr)
        # 中文：优先2字重复，再单字重复（顺序不能调换！）
        curr = re.sub(r'([\u4e00-\u9fff]{2})\1+', r'\1', curr)
        curr = re.sub(r'([\u4e00-\u9fff])\1+', r'\1', curr)
    return curr


def normalize_text(text: Optional[str]) -> str:
    """基础清洗：全角空格转半角、压缩连续空白、去首尾空白；
    新增ASR场景处理：spk标记、[噪音]/[静音]/<unk>噪声标记清除，调用dedup_asr_repeats去除连续重复。
    None 或空字符串返回 ""。
    """
    if text is None or not isinstance(text, str):
        return ""
    t = text
    # 清洗ASR常见标记噪声，按需开启
    t = re.sub(r"\[spk\d+\]", " ", t)
    t = re.sub(r"\[噪音\]|\[静音\]|<unk>", " ", t)
    # 全角空格转半角 + 合并空白
    t = re.sub(r"[　]", " ", t)
    t = re.sub(r"\s+", " ", t)
    t = t.strip()
    t = dedup_asr_repeats(t)
    return t


def tokenize(text: Optional[str], remove_filler: bool = True) -> List[str]:
    """中文分词。
    装了 jieba 时用 jieba；没装时先按空白切分（中文句子会变成
    一整个词，效果差 —— 这是临时降级方案）。
    :param remove_filler: 是否过滤ASR口语填充词/语气词，默认开启
    """
    cleaned = normalize_text(text)
    if not cleaned:
        return []
    try:
        words = [w for w in jieba.cut(cleaned) if w.strip()]
    except ImportError:
        # jieba不可用时降级：按空格切，无中文分词
        words = [w for w in cleaned.split(" ") if w.strip()]
    # ASR口语填充词/语气词，扩充版本
    _FILLER = {
        "嗯", "啊", "呃", "噢", "哦", "哎呀", "哎",
        "那个", "就是", "就是说", "然后", "所以", "其实",
        "对吧", "是不是", "你知道", "呃对", "算了", "嗯对"
    }
    if remove_filler:
        words = [w for w in words if w not in _FILLER]
    return words

