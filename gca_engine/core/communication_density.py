"""
GCA — Communication Density (paper Step 12)。从 ami_parser 迁移（旧基线）。

Contribution-level:

    D_t = ||d_t|| / ||c_t||

where ||c_t|| is the contribution's word count.  Word count follows
the project's fixed LSA preprocessing tokenizer (config word_count =
"preprocessed_tokens") — a project implementation convention, not an
original-GCA-specified tokenization.  Participant-level density is the
ratio of TOTALS, not the mean of contribution densities:

    D(a) = sum_{t: speaker(t)=a} ||d_t|| / sum_{t: speaker(t)=a} ||c_t||

Zero word counts resolve to 0.0 (zero-vector policy); no NaN / Inf is
ever produced.
"""

from collections.abc import Sequence

import numpy as np

from gca_engine.core.config import validate_zero_vector_policy


def contribution_density(
    vectors: np.ndarray, word_counts: Sequence[float], zero_vector_policy: str = "zero",
) -> np.ndarray:
    """Contribution-level density D_t = ||d_t|| / word_count_t (length-n)."""
    validate_zero_vector_policy(zero_vector_policy)
    d = np.asarray(vectors, dtype=float)
    counts = np.asarray(word_counts, dtype=float)
    if d.ndim != 2 or counts.ndim != 1 or d.shape[0] != counts.shape[0]:
        raise ValueError(
            f"vectors (n, d) and word_counts (n,) must align, got "
            f"{d.shape} and {counts.shape}"
        )
    norms = np.linalg.norm(d, axis=1)
    density = np.zeros(d.shape[0], dtype=float)
    has_words = counts > 0
    density[has_words] = norms[has_words] / counts[has_words]
    return density


def participant_density(
    vectors: np.ndarray,
    word_counts: Sequence[float],
    speakers: Sequence[str],
    zero_vector_policy: str = "zero",
) -> dict[str, float]:
    """Participant density: total semantic norm / total word count."""
    validate_zero_vector_policy(zero_vector_policy)
    d = np.asarray(vectors, dtype=float)
    counts = np.asarray(word_counts, dtype=float)
    norms = np.linalg.norm(d, axis=1)
    order = sorted(set(speakers))
    out = {}
    for s in order:
        mask = np.array([sp == s for sp in speakers], dtype=bool)
        total_words = counts[mask].sum()
        out[s] = float(norms[mask].sum() / total_words) if total_words > 0 else 0.0
    return out
