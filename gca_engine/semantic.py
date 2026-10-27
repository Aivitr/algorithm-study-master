"""
gca_engine.semantic —— LSA 语义空间入口（负责人：陈虹宇）。

把 core/lsa 的 LSAModel 包成引擎可直接用的两个函数：
    fit_lsa_space   在一批原始文本上拟合语义空间
    project_texts   把文本投影进已拟合的空间

后续计划（参考旧实验的 unified_lsa 思路）：
用全部历史课堂发言拟合一个统一语义空间，再投影每次课，
避免每节课单独拟合导致不同课之间向量不可比。
"""

import numpy as np

from gca_engine.core.lsa import LSAConfig, LSAModel


def fit_lsa_space(
    corpus_texts: list[str],
    config: LSAConfig | None = None,
) -> LSAModel:
    """在一批原始文本上拟合 LSA 语义空间（TF-IDF + TruncatedSVD）。

    Args:
        corpus_texts: 语料文本（原始文本，清洗在模型内部完成）。
        config:       可选 LSAConfig；默认与旧基线一致。

    Returns:
        已拟合的 LSAModel（可用 project_texts 投影）。
    """
    model = LSAModel(config or LSAConfig())
    model.fit(list(corpus_texts))
    return model


def project_texts(model: LSAModel, texts: list[str]) -> np.ndarray:
    """把文本投影进已拟合的 LSA 空间。

    Returns:
        (len(texts), actual_dimensions) 的 float 数组。
        清洗后为空的文本对应全零向量。
    """
    return model.transform(list(texts))
