"""
LSA semantic space —— 从 ami_parser 迁移（数学与旧基线一致）。

Implements the classical LSA pipeline:

    preprocessed documents → TF-IDF (Document-Term Matrix)
                           → TruncatedSVD
                           → fixed-dimensional semantic vectors

Corpus and target documents are strictly separated: the model is fitted
once on a corpus, then any number of target utterances are projected into
the same semantic space (no per-utterance fitting — no data leakage).

与旧版不同的是：
- 不再依赖 AMI 的 models.schema（Conversation）；
- 移除了 matplotlib 绘图（plot_semantic_space）和 AMI 目录版
  run_lsa_pipeline，这些仍保留在旧目录 final/ami_parser。
"""

import logging
from pathlib import Path

import joblib
import numpy as np
from sklearn.decomposition import TruncatedSVD

from gca_engine.core.lsa.config import LSAConfig
from gca_engine.core.lsa.preprocessing import clean_text
from gca_engine.core.lsa.vectorizer import TfidfStage

logger = logging.getLogger(__name__)


class LSAModel:
    """TF-IDF + TruncatedSVD pipeline with explicit fit / transform phases."""

    def __init__(self, config: LSAConfig | None = None):
        self.config = config or LSAConfig()
        self.tfidf = TfidfStage(self.config)

        self.svd: TruncatedSVD | None = None
        self.requested_dimensions: int = self.config.n_components
        self.actual_dimensions: int | None = None
        self.corpus_metadata: dict = {}

    # ------------------------------------------------------------------
    # Fit / transform
    # ------------------------------------------------------------------

    def _preprocess(self, documents: list[str]) -> list[str]:
        cfg = self.config
        return [
            clean_text(d, lowercase=cfg.lowercase,
                       remove_punctuation=cfg.remove_punctuation)
            for d in documents
        ]

    @staticmethod
    def _max_feasible_dimensions(n_samples: int, n_features: int) -> int:
        """Largest n_components legal for both SVD solvers.

        ``arpack`` requires n_components < min(n_samples, n_features);
        ``randomized`` requires n_components < n_features.  Using
        ``min(n_samples, n_features) - 1`` is the conservative bound.
        """
        return max(min(n_samples, n_features) - 1, 1)

    def fit(self, corpus_documents: list[str]) -> dict:
        """Fit TF-IDF and SVD on the corpus documents.

        Args:
            corpus_documents: Raw corpus texts (one per document).

        Returns:
            Fit summary dict (recorded in ``corpus_metadata``).

        Raises:
            ValueError: If the corpus has no usable (non-empty) documents.
        """
        docs = self._preprocess(corpus_documents)
        self.tfidf.fit(docs)
        matrix = self.tfidf.transform(docs)

        n_samples, n_features = matrix.shape
        max_dim = self._max_feasible_dimensions(n_samples, n_features)

        requested = self.config.n_components
        if requested > max_dim:
            logger.warning(
                "requested n_components=%d exceeds max feasible %d "
                "(min(n_samples=%d, n_features=%d) - 1); clamping to %d",
                requested, max_dim, n_samples, n_features, max_dim,
            )
            actual = max_dim
        else:
            actual = requested

        self.actual_dimensions = actual
        self.svd = TruncatedSVD(
            n_components=actual,
            algorithm=self.config.algorithm,
            random_state=self.config.random_state,
        )
        self.svd.fit(matrix)

        self.corpus_metadata = {
            "n_corpus_documents": n_samples,
            "n_features": n_features,
            "tfidf_shape": [n_samples, n_features],
            "requested_dimensions": requested,
            "actual_dimensions": actual,
            "max_feasible_dimensions": max_dim,
        }
        logger.info("LSA fitted: %s", self.corpus_metadata)
        return dict(self.corpus_metadata)

    def transform(self, documents: list[str]) -> np.ndarray:
        """Project *documents* into the fitted LSA space.

        Returns:
            Dense array of shape ``(len(documents), actual_dimensions)``.
            Documents that preprocess to empty text map to zero vectors.

        Raises:
            RuntimeError: If the model has not been fitted.
        """
        if self.svd is None or self.actual_dimensions is None:
            raise RuntimeError("LSAModel is not fitted — call fit() first")

        docs = self._preprocess(documents)
        tfidf_matrix = self.tfidf.transform(docs)
        vectors = self.svd.transform(tfidf_matrix)
        return vectors

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_model(self, model_dir: Path) -> None:
        """Persist the fitted TF-IDF vectorizer and SVD model via joblib."""
        if self.svd is None:
            raise RuntimeError("LSAModel is not fitted — nothing to save")
        model_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.tfidf.vectorizer, model_dir / "vectorizer.joblib")
        joblib.dump(self.svd, model_dir / "svd.joblib")
        logger.info("model saved to %s", model_dir)

    @classmethod
    def load(cls, model_dir: Path, config: LSAConfig | None = None) -> "LSAModel":
        """Rebuild a fitted LSAModel from saved vectorizer / SVD files.

        The loaded model supports ``transform()`` only — TF-IDF
        statistics (``tfidf.stats``) are not restored.
        """
        model = cls(config)
        model.tfidf.load_vectorizer(model_dir / "vectorizer.joblib")
        model.svd = joblib.load(model_dir / "svd.joblib")
        model.actual_dimensions = int(model.svd.n_components)
        logger.info("LSA model loaded from %s (dims=%d)",
                    model_dir, model.actual_dimensions)
        return model


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def run_verification_checks(
    vectors: np.ndarray,
    speakers: list[str],
    model: LSAModel,
    deterministic: bool,
) -> dict:
    """Run the mandatory post-LSA checks.

    Args:
        vectors:      (n, d) LSA vectors, index-aligned with speakers.
        speakers:     Length-n speaker sequence.
        model:        The fitted LSAModel.
        deterministic: Whether a deterministic re-fit passed.

    Returns:
        Dict of check name -> PASS/FAIL plus summary statistics.
    """
    n_utterances = len(speakers)

    # Check 1: vector count equals utterance count
    check1 = "PASS" if vectors.shape[0] == n_utterances else "FAIL"

    # Check 2: every utterance has a corresponding vector (index-aligned)
    check2 = "PASS" if vectors.shape[0] == n_utterances and vectors.ndim == 2 else "FAIL"

    # Check 3: vector shape is [n_utterances, actual_dimensions]
    expected_shape = (n_utterances, model.actual_dimensions)
    check3 = "PASS" if vectors.shape == expected_shape else "FAIL"

    # Check 4: no NaN / Inf
    n_nan = int(np.isnan(vectors).sum())
    n_inf = int(np.isinf(vectors).sum())
    check4 = "PASS" if (n_nan == 0 and n_inf == 0) else "FAIL"

    # Check 5: deterministic re-fit (passed in by the pipeline)
    check5 = "PASS" if deterministic else "FAIL"

    # Check 6: speaker information recoverable per vector index
    speakers_ok = all(isinstance(s, str) and s for s in speakers)
    check6 = "PASS" if speakers_ok and n_utterances > 0 else "FAIL"

    # Check 7: summary statistics
    stats = {
        "n_utterances": n_utterances,
        "n_speakers": len(set(speakers)),
        "vocabulary_size": model.tfidf.stats.vocabulary_size if model.tfidf.stats else None,
        "tfidf_shape": list(model.tfidf.stats.matrix_shape) if model.tfidf.stats else None,
        "requested_dimensions": model.requested_dimensions,
        "actual_dimensions": model.actual_dimensions,
        "vector_shape": list(vectors.shape),
        "n_nan": n_nan,
        "n_inf": n_inf,
    }

    checks = {
        "check1_utterance_count": check1,
        "check2_per_utterance_vector": check2,
        "check3_vector_shape": check3,
        "check4_no_nan_inf": check4,
        "check5_deterministic": check5,
        "check6_speaker_mapping": check6,
    }
    all_pass = all(v == "PASS" for v in checks.values())
    logger.info("LSA verification: %s", checks)

    return {"checks": checks, "overall": "PASS" if all_pass else "FAIL", "stats": stats}
