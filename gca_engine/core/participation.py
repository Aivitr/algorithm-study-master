"""
GCA — Participation (paper Step 4)。从 ami_parser 原样迁移（旧基线）。

Binary participation sequence p_t(a) = 1 iff contribution t was made
by participant a; mean participation of a = count(a) / n, where
count(a) = sum_t p_t(a).
"""

from collections.abc import Sequence

import numpy as np


def participation_series(speakers: Sequence[str]) -> tuple[list[str], dict[str, np.ndarray]]:
    """Binary participation series per participant.

    Returns:
        (speaker_order, series): ``series[a]`` is a boolean length-n
        array with ``series[a][t] == (speakers[t] == a)``.
    """
    order = sorted(set(speakers))
    if not order:
        raise ValueError("participation needs at least one contribution")
    index = {s: i for i, s in enumerate(order)}
    n = len(speakers)
    matrix = np.zeros((n, len(order)), dtype=bool)
    for t, s in enumerate(speakers):
        matrix[t, index[s]] = True
    return order, {s: matrix[:, i] for i, s in enumerate(order)}


def participation(speakers: Sequence[str]) -> dict[str, float]:
    """Mean participation per participant: count(a) / n."""
    order, series = participation_series(speakers)
    n = len(speakers)
    return {s: float(series[s].sum()) / n for s in order}
