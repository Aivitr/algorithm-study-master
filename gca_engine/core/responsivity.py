"""
GCA — Lagged / w-spanning Responsivity and derived metrics
(paper Steps 6-10)。从 ami_parser 迁移（旧基线）。

For lag tau, contribution t is paired with contribution t - tau.  A
pair belongs to "a responds to b at lag tau" iff speaker(t) == a and
speaker(t - tau) == b.  Strict orientation: row = respondent, column =
initiator:

    R_tau[a, b] = mean cosine(d_t, d_(t-tau)) over such pairs,
                  or 0.0 if there are no pairs.

The w-spanning matrix averages R_tau over ALL lags tau = 1..w —
including lags without pairs, which contribute 0:

    R_bar_w = (1/w) * sum_{tau=1..w} R_tau

Derived participant metrics:

    Internal Cohesion    = diagonal of R_bar_w        (R_bar_w[a, a])
    Overall Responsivity = row mean, diagonal excluded (respondent view)
    Social Impact        = column mean, diagonal excluded (initiator view)
"""

from collections.abc import Sequence

import numpy as np

from gca_engine.core.similarity import pairwise_cosine


def _speaker_index(speakers: Sequence[str]) -> tuple[list[str], dict[str, int]]:
    order = sorted(set(speakers))
    return order, {s: i for i, s in enumerate(order)}


def lagged_responsivity(
    speakers: Sequence[str],
    vectors: np.ndarray,
    tau: int,
    zero_vector_policy: str = "zero",
) -> tuple[list[str], np.ndarray, int]:
    """Compute R_tau for a single lag.

    Args:
        speakers: Length-n speaker sequence in utterance order.
        vectors:  (n, d) contribution vectors, index-aligned.
        tau:      Lag >= 1.

    Returns:
        (speaker_order, R_tau, n_zero_vector_pairs) — R_tau is a k×k
        array indexed [row=respondent, col=initiator].
    """
    if tau < 1:
        raise ValueError(f"tau must be >= 1, got {tau}")
    n = len(speakers)
    order, index = _speaker_index(speakers)
    k = len(order)
    r_tau = np.zeros((k, k), dtype=float)
    n_zero_pairs = 0
    if n > tau:
        respondents = np.array([index[s] for s in speakers[tau:]], dtype=int)
        initiators = np.array([index[s] for s in speakers[:-tau]], dtype=int)
        cosines, undefined = pairwise_cosine(
            vectors[tau:], vectors[:-tau], zero_vector_policy=zero_vector_policy
        )
        n_zero_pairs = int(undefined.sum())
        counts = np.zeros((k, k), dtype=float)
        sums = np.zeros((k, k), dtype=float)
        np.add.at(counts, (respondents, initiators), 1.0)
        np.add.at(sums, (respondents, initiators), cosines)
        has_pairs = counts > 0
        r_tau[has_pairs] = sums[has_pairs] / counts[has_pairs]
    return order, r_tau, n_zero_pairs


def spanning_responsivity(
    speakers: Sequence[str],
    vectors: np.ndarray,
    window: int,
    zero_vector_policy: str = "zero",
) -> tuple[list[str], list[np.ndarray], np.ndarray, int]:
    """R_bar_w = (1/w) * sum_{tau=1..w} R_tau (all lags averaged).

    Returns:
        (speaker_order, [R_1..R_w], R_bar_w, total_zero_vector_pairs).
    """
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    order = None
    matrices: list[np.ndarray] = []
    total_zero_pairs = 0
    for tau in range(1, window + 1):
        order, r_tau, n_zero = lagged_responsivity(
            speakers, vectors, tau, zero_vector_policy=zero_vector_policy
        )
        matrices.append(r_tau)
        total_zero_pairs += n_zero
    r_bar = np.mean(np.stack(matrices), axis=0)
    return order, matrices, r_bar, total_zero_pairs


def internal_cohesion(r_bar: np.ndarray, speakers: Sequence[str]) -> dict[str, float]:
    """Internal cohesion: diagonal of the w-spanning matrix."""
    order, index = _speaker_index(speakers)
    return {s: float(r_bar[index[s], index[s]]) for s in order}


def overall_responsivity(r_bar: np.ndarray, speakers: Sequence[str]) -> dict[str, float]:
    """Overall responsivity: row mean of R_bar_w, diagonal excluded."""
    order, index = _speaker_index(speakers)
    if len(order) == 1:
        return {order[0]: 0.0}
    out = {}
    for s in order:
        i = index[s]
        out[s] = float(np.delete(r_bar[i], i).mean())
    return out


def social_impact(r_bar: np.ndarray, speakers: Sequence[str]) -> dict[str, float]:
    """Social impact: column mean of R_bar_w, diagonal excluded."""
    order, index = _speaker_index(speakers)
    if len(order) == 1:
        return {order[0]: 0.0}
    out = {}
    for s in order:
        j = index[s]
        out[s] = float(np.delete(r_bar[:, j], j).mean())
    return out
