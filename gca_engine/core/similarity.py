"""
GCA — cosine semantic similarity (paper Step 5)。从 ami_parser 迁移（旧基线）。

Cosine between contribution vectors with an explicit zero-vector
policy.  PROJECT IMPLEMENTATION CONVENTION (not an original-GCA
specification): the cosine is undefined for zero-vector pairs, and
this project deterministically assigns similarity 0.0
(zero_vector_policy "zero").  NaN is never produced; undefined
positions are reported so zero-vector pairs can be counted.
"""

import numpy as np

from gca_engine.core.config import ZERO_EPS, validate_zero_vector_policy


def cosine(d_i, d_j, zero_vector_policy: str = "zero") -> float:
    """Cosine similarity between two single contribution vectors."""
    cosines, _ = pairwise_cosine(
        np.asarray(d_i, dtype=float).reshape(1, -1),
        np.asarray(d_j, dtype=float).reshape(1, -1),
        zero_vector_policy=zero_vector_policy,
    )
    return float(cosines[0])


def pairwise_cosine(x, y, zero_vector_policy: str = "zero"):
    """Row-wise cosine between two equal-shaped (m, d) arrays.

    Returns:
        (cosines, undefined_mask): ``undefined_mask[i]`` is True where
        row i of x or y has zero norm (cosine undefined; policy "zero"
        sets the cosine to 0.0).
    """
    validate_zero_vector_policy(zero_vector_policy)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.ndim != 2 or y.ndim != 2 or x.shape != y.shape:
        raise ValueError(
            "pairwise_cosine needs equal-shaped 2-D arrays, "
            f"got {x.shape} and {y.shape}"
        )
    nx = np.linalg.norm(x, axis=1)
    ny = np.linalg.norm(y, axis=1)
    undefined = (nx <= ZERO_EPS) | (ny <= ZERO_EPS)
    dots = np.einsum("ij,ij->i", x, y)
    cosines = np.zeros(x.shape[0], dtype=float)
    defined = ~undefined
    cosines[defined] = dots[defined] / (nx[defined] * ny[defined])
    return cosines, undefined
