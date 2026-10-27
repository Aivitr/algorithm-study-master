"""
GCA — orchestration of the six GCA metrics (paper Step 13)。
从 ami_parser 迁移（数学与旧基线一致）。

compute_gca_metrics() is the pure mathematical core: it takes a
speaker sequence, the aligned unified-LSA vectors and the aligned word
counts, and returns the six participant-level metrics plus the raw
intermediates (R_tau, R_bar_w, contribution-level newness and
density).

旧版的 run_gca_for_meeting()（从 AMI 目录读磁盘）留在旧目录
final/ami_parser，新引擎用 gca_engine/engine.py 在内存里完成
同样的流程。
"""

import logging
from dataclasses import asdict, dataclass

import numpy as np

from gca_engine.core.communication_density import (
    contribution_density,
    participant_density,
)
from gca_engine.core.config import GCAConfig, ZERO_EPS
from gca_engine.core.newness import contribution_newness, participant_newness
from gca_engine.core.participation import participation, participation_series
from gca_engine.core.responsivity import (
    internal_cohesion,
    overall_responsivity,
    social_impact,
    spanning_responsivity,
)

logger = logging.getLogger(__name__)


@dataclass
class GCAResult:
    """All six GCA metrics for one meeting plus raw intermediates.

    Field values are JSON-serializable (arrays are stored as lists);
    call :meth:`to_dict` for a plain-dict snapshot.
    """

    meeting_id: str
    speakers: list[str]
    n_utterances: int
    config: dict
    participation: dict[str, float]
    participation_series: dict[str, list[bool]]
    responsivity_lags: list[list[list[float]]]  # R_1..R_w (k×k)
    responsivity_matrix: list[list[float]]      # R_bar_w (k×k)
    internal_cohesion: dict[str, float]
    overall_responsivity: dict[str, float]
    social_impact: dict[str, float]
    newness: list[float]                        # contribution-level
    newness_by_speaker: dict[str, float]
    density: list[float]                        # contribution-level
    density_by_speaker: dict[str, float]
    zero_vector: dict

    def to_dict(self) -> dict:
        return asdict(self)


def compute_gca_metrics(
    meeting_id: str,
    speakers: list[str],
    vectors: np.ndarray,
    word_counts: list[float],
    config: GCAConfig | None = None,
) -> GCAResult:
    """Compute the six GCA metrics for one meeting.

    Args:
        meeting_id:  Meeting identifier (recorded, not used by the maths).
        speakers:    Length-n speaker sequence in utterance order.
        vectors:     (n, d) unified-LSA vectors, index-aligned.
        word_counts: Length-n word counts (word_count definition from
                     config: preprocessed LSA tokens).
        config:      Optional GCAConfig.
    """
    config = config or GCAConfig()
    speakers = list(speakers)
    vectors = np.asarray(vectors, dtype=float)
    word_counts = np.asarray(word_counts, dtype=float)
    n = len(speakers)
    if n == 0:
        raise ValueError("cannot compute GCA metrics for an empty meeting")
    if vectors.ndim != 2 or vectors.shape[0] != n:
        raise ValueError(f"vectors must be (n={n}, d), got shape {vectors.shape}")
    if word_counts.shape != (n,):
        raise ValueError(
            f"word_counts must have length n={n}, got shape {word_counts.shape}"
        )

    order = sorted(set(speakers))
    _, part_series = participation_series(speakers)
    part = participation(speakers)

    _, r_lags, r_bar, n_zero_pairs = spanning_responsivity(
        speakers, vectors, config.spanning_window, config.zero_vector_policy
    )
    cohesion = internal_cohesion(r_bar, speakers)
    or_metric = overall_responsivity(r_bar, speakers)
    si = social_impact(r_bar, speakers)

    newness_arr = contribution_newness(vectors, config.zero_vector_policy)
    n_by_speaker = participant_newness(newness_arr, speakers)

    density_arr = contribution_density(vectors, word_counts, config.zero_vector_policy)
    d_by_speaker = participant_density(
        vectors, word_counts, speakers, config.zero_vector_policy
    )

    norms = np.linalg.norm(vectors, axis=1)
    zero_vector_stats = {
        "policy": config.zero_vector_policy,
        "n_zero_vectors": int((norms <= ZERO_EPS).sum()),
        "zero_vector_indices": [int(i) for i in range(n) if norms[i] <= ZERO_EPS],
        "n_zero_word_counts": int((word_counts <= 0).sum()),
        "zero_word_count_indices": [int(i) for i in range(n) if word_counts[i] <= 0],
        "n_zero_vector_similarity_pairs": int(n_zero_pairs),
        "affected_metrics": ["responsivity", "newness", "communication_density"],
    }

    return GCAResult(
        meeting_id=meeting_id,
        speakers=order,
        n_utterances=n,
        config=config.to_dict(),
        participation=part,
        participation_series={s: part_series[s].tolist() for s in order},
        responsivity_lags=[m.tolist() for m in r_lags],
        responsivity_matrix=r_bar.tolist(),
        internal_cohesion=cohesion,
        overall_responsivity=or_metric,
        social_impact=si,
        newness=newness_arr.tolist(),
        newness_by_speaker=n_by_speaker,
        density=density_arr.tolist(),
        density_by_speaker=d_by_speaker,
        zero_vector=zero_vector_stats,
    )
