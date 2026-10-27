"""
TF-IDF stage —— 从 ami_parser 迁移（旧基线）。

Wraps scikit-learn's TfidfVectorizer as the Document-Term Matrix step.
Receives *already preprocessed* documents; tokenization is plain
whitespace splitting so preprocessing.py remains the single source of
truth for text cleaning.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer

from gca_engine.core.lsa.config import LSAConfig

logger = logging.getLogger(__name__)


@dataclass
class TfidfStats:
    """Summary of a fitted TF-IDF stage."""

    n_documents: int
    matrix_shape: tuple[int, int]
    vocabulary_size: int
    feature_names: list[str] = field(default_factory=list)


class TfidfStage:
    """Fit-once / transform-many TF-IDF document-term matrix stage."""

    def __init__(self, config: LSAConfig):
        self._config = config
        self._vectorizer: TfidfVectorizer | None = None
        self.stats: TfidfStats | None = None

    @property
    def vectorizer(self) -> TfidfVectorizer:
        """The fitted sklearn vectorizer (for model persistence)."""
        if self._vectorizer is None:
            raise RuntimeError("TfidfStage is not fitted")
        return self._vectorizer

    def _build_vectorizer(self) -> TfidfVectorizer:
        cfg = self._config
        return TfidfVectorizer(
            # Documents arrive preprocessed; split on whitespace only.
            token_pattern=r"\S+",
            lowercase=False,
            stop_words=cfg.stop_words,
            min_df=cfg.min_df,
            max_df=cfg.max_df,
            max_features=cfg.max_features,
            sublinear_tf=cfg.sublinear_tf,
            use_idf=cfg.use_idf,
            norm=cfg.norm,
        )

    def fit(self, documents: list[str]) -> TfidfStats:
        """Build the vocabulary and IDF weights from *documents*."""
        if not any(d.strip() for d in documents):
            raise ValueError(
                "TF-IDF fit failed: corpus contains no non-empty documents"
            )

        self._vectorizer = self._build_vectorizer()
        matrix = self._vectorizer.fit_transform(documents)

        self.stats = TfidfStats(
            n_documents=matrix.shape[0],
            matrix_shape=tuple(matrix.shape),
            vocabulary_size=len(self._vectorizer.vocabulary_),
            feature_names=list(self._vectorizer.get_feature_names_out()),
        )
        logger.info("TF-IDF fitted: matrix=%s vocabulary=%d",
                    self.stats.matrix_shape, self.stats.vocabulary_size)
        return self.stats

    def transform(self, documents: list[str]) -> sparse.csr_matrix:
        """Project *documents* into the fitted TF-IDF space.

        Documents not seen at fit time contribute nothing to the matrix
        rows (standard TF-IDF behaviour).
        """
        if self._vectorizer is None:
            raise RuntimeError("TfidfStage is not fitted — call fit() first")
        return self._vectorizer.transform(documents)

    def load_vectorizer(self, path: Path) -> None:
        """Restore a fitted vectorizer from a joblib file."""
        self._vectorizer = joblib.load(path)
        logger.info("vectorizer loaded from %s", path)
