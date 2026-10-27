"""
GCA — Newness / Sharing of New Information (paper Step 11)。
从 ami_parser 迁移（旧基线，数学原样保留）。

Previous contribution vectors span a subspace G_t; the current vector
d_t decomposes orthogonally into

    d_t = g_t + n_t      (g_t in G_t, n_t in the orthogonal complement)

and the contribution newness is

    newness(c_t) = ||n_t|| / (||n_t|| + ||g_t||)      in [0, 1]

The projection uses a numerically stable orthonormal basis of G_t from
QR decomposition — never the explicit projection matrix A(A^T A)^-1
A^T.  Zero vectors in the history span nothing and are excluded from
the basis; linearly dependent histories are handled by QR itself.

t = 1 has no previous subspace (empty historical subspace): this
project deterministically assigns newness 1.0 — an implementation
convention, NOT an original-GCA-specified value (recorded in
``GCAConfig.NOTES``).  A zero first vector is 0.0 by the zero-vector
policy.  No NaN is ever produced.

Participant-level newness N(a) = mean of newness(c_t) over the
contributions of participant a.
"""

from collections.abc import Sequence

import numpy as np

from gca_engine.core.config import ZERO_EPS, validate_zero_vector_policy


def contribution_newness(vectors: np.ndarray, zero_vector_policy: str = "zero") -> np.ndarray:
    """Newness for every contribution (length-n array)."""
    validate_zero_vector_policy(zero_vector_policy)
    d = np.asarray(vectors, dtype=float)
    if d.ndim != 2:
        raise ValueError(f"vectors must be a 2-D array, got shape {d.shape}")
    n = d.shape[0]
    newness = np.zeros(n, dtype=float)
    for t in range(n):
        d_t = d[t]
        if np.linalg.norm(d_t) <= ZERO_EPS:
            newness[t] = 0.0  # zero-vector policy: nothing new, no NaN
            continue
        if t == 0:
            newness[t] = 1.0  # deterministic: no previous subspace
            continue
        history = d[:t]
        basis = history[np.linalg.norm(history, axis=1) > ZERO_EPS]
        if basis.shape[0] == 0:
            newness[t] = 1.0
            continue
        q, r = np.linalg.qr(basis.T, mode="reduced")
        # Householder QR of a rank-deficient input fills the columns
        # beyond the rank with arbitrary orthonormal completions, so the
        # projection basis must be truncated to the rank of R.
        diag = np.abs(np.diag(r))
        rank = int((diag > ZERO_EPS * diag.max()).sum())
        q_basis = q[:, :rank]
        g = q_basis @ (q_basis.T @ d_t)
        residual = d_t - g
        newness[t] = float(
            np.linalg.norm(residual) / (np.linalg.norm(residual) + np.linalg.norm(g))
        )
    return np.clip(newness, 0.0, 1.0)


def participant_newness(
    newness_array: np.ndarray, speakers: Sequence[str],
) -> dict[str, float]:
    """N(a) = mean contribution newness over participant a's contributions."""
    arr = np.asarray(newness_array, dtype=float)
    order = sorted(set(speakers))
    out = {}
    for s in order:
        mask = np.array([sp == s for sp in speakers], dtype=bool)
        out[s] = float(arr[mask].mean()) if mask.any() else 0.0
    return out
