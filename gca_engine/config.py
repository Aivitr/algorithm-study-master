"""
gca_engine 引擎级配置（负责人：雷梦琪）。

注意区分三个 config，不要混用：
- gca_engine/config.py            引擎总配置（本文件）
- gca_engine/core/config.py       GCA 数学参数（GCAConfig，旧基线）
- gca_engine/core/lsa/config.py   LSA 参数（LSAConfig，旧基线）
"""

from dataclasses import asdict, dataclass

# 时间窗口默认值（第一版约定）
FIXED_WINDOW_SECONDS = 300    # 固定 5 分钟窗口
SLIDING_WINDOW_SECONDS = 300  # 滑动 5 分钟窗口
SLIDING_STEP_SECONDS = 30     # 滑动窗口每 30 秒一个更新点（首版，后续按性能调整）


@dataclass
class EngineConfig:
    """引擎总配置。

    v0.1 用到 min_utterances / lsa_components；
    v0.2 加上时间窗口的开关和粒度。
    """

    fixed_window_seconds: int = FIXED_WINDOW_SECONDS
    sliding_window_seconds: int = SLIDING_WINDOW_SECONDS
    sliding_step_seconds: int = SLIDING_STEP_SECONDS
    min_utterances: int = 2   # 少于这个数直接 insufficient_data
    lsa_components: int = 300  # 与旧基线 LSAConfig 默认一致；小语料自动降维
    # 是否计算 timeline。窗口计算比整节课多花 O(窗口数 × 发言数)，
    # 只需要个人/小组指标、不要时间趋势的调用方可以关掉。
    timeline_enabled: bool = True
    # 分词方案：
    #   "chinese" —— 旧清洗（小写 + 去标点）后交给 preprocessing/chinese.py
    #                的 tokenize（装了 jieba 就真分词，没装自动退回按空白切）
    #   "legacy"  —— 旧基线：core/lsa 的空白分词，用于复现历史结果、对比基线
    tokenizer: str = "chinese"

    def to_dict(self) -> dict:
        return asdict(self)
