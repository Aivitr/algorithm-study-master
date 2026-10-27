"""
GCA configuration —— 从 ami_parser 原样迁移（旧基线，勿改数学）。

Every tunable experiment parameter lives here so that a GCA run is
fully described by its config snapshot (reproducibility requirement).

Provenance: the metric mathematics follows the original GCA method
(Dowell, Nixon & Graesser) — participation, lagged / w-spanning
responsivity, internal cohesion, overall responsivity, social impact,
LSA given-new newness and communication density, with row = respondent
/ column = initiator and a trailing w-spanning window.  Three details
are PROJECT IMPLEMENTATION CONVENTIONS, not original-GCA-specified
values (recorded in ``GCAConfig.NOTES`` and in each run's config
snapshot):

* first-contribution newness = 1.0 for an empty historical subspace;
* zero vectors: undefined cosine pairs are deterministically assigned
  similarity 0.0 (zero_vector_policy "zero");
* word count follows the project's fixed LSA preprocessing tokenizer.
"""

from dataclasses import asdict, dataclass
from typing import ClassVar

# Vectors with Euclidean norm <= ZERO_EPS are treated as zero vectors.
ZERO_EPS = 1e-12

# Supported zero-vector policies.  "zero": vectors are left unmodified;
# wherever the maths is undefined for a zero vector (cosine denominator,
# newness 0/0, density 0/0) the metric value is deterministically 0.0 —
# never NaN.
ZERO_VECTOR_POLICIES = ("zero",)


def validate_zero_vector_policy(policy: str) -> None:
    """Raise ValueError for unsupported zero-vector policies."""
    if policy not in ZERO_VECTOR_POLICIES:
        raise ValueError(
            f"zero_vector_policy must be one of {ZERO_VECTOR_POLICIES}, "
            f"got {policy!r}"
        )


@dataclass
class GCAConfig:
    """All parameters controlling the GCA metric computation.

    Attributes:
        spanning_window:    Number of lags tau = 1..w averaged into the
                            w-spanning responsivity matrix.  Default 20
                            is the original GCA-calibrated value.
        zero_vector_policy: How undefined zero-vector maths is resolved.
                            Only "zero" is implemented (see above) —
                            a project convention, not an original-GCA
                            specification.
        word_count:         Word-count definition used for communication
                            density: "preprocessed_tokens" = number of
                            whitespace-separated tokens after the LSA
                            preprocessing — the project's fixed LSA
                            tokenizer; no new tokenizer is introduced.
    """

    spanning_window: int = 20
    zero_vector_policy: str = "zero"
    word_count: str = "preprocessed_tokens"

    # Provenance of each configuration choice (see module docstring).
    NOTES: ClassVar[dict] = {
        "spanning_window": "original GCA-calibrated value (w=20)",
        "zero_vector_policy": "project implementation convention",
        "word_count": "project's fixed LSA preprocessing tokenizer",
        "first_contribution_newness": (
            "project implementation convention (1.0 for empty historical subspace)"
        ),
    }

    def __post_init__(self) -> None:
        if self.spanning_window < 1:
            raise ValueError(
                f"spanning_window must be >= 1, got {self.spanning_window}"
            )
        validate_zero_vector_policy(self.zero_vector_policy)
        if self.word_count != "preprocessed_tokens":
            raise ValueError(
                "word_count must be 'preprocessed_tokens' "
                f"(the LSA preprocessing tokenizer), got {self.word_count!r}"
            )

    def to_dict(self) -> dict:
        """Plain-dict representation for JSON serialization."""
        d = asdict(self)
        d["notes"] = dict(self.NOTES)
        return d
