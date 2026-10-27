"""
LSA pipeline configuration —— 从 ami_parser 原样迁移（旧基线）。

Every tunable experiment parameter lives here so that a run is fully
described by its saved ``lsa_config.json`` (reproducibility requirement).
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class LSAConfig:
    """All parameters controlling the LSA pipeline.

    Attributes:
        n_components:      Requested LSA dimensionality (target: 300).
                           The pipeline clamps this to the largest legal
                           value for the fitted corpus and records both
                           requested and actual dimensions.
        algorithm:         TruncatedSVD solver: "randomized" (default) or
                           "arpack".  "randomized" needs random_state for
                           reproducibility.
        random_state:      Fixed seed for deterministic SVD.
        lowercase:         Lowercase text before tokenization.
        remove_punctuation: Strip punctuation characters from text.
        stop_words:        ``None`` keeps every token (chosen default for
                           transparency); ``"english"`` uses scikit-learn's
                           standard English stop-word list.
        min_df:            Minimum document frequency for TF-IDF terms.
        max_df:            Maximum document frequency (proportion).
        max_features:      Cap on vocabulary size (None = unlimited).
        sublinear_tf:      Use 1+log(tf) scaling.
        use_idf:           Enable IDF weighting.
        norm:              TF-IDF row normalization ("l2" or None).
    """

    # --- SVD / LSA ------------------------------------------------------
    n_components: int = 300
    algorithm: str = "randomized"
    random_state: int = 42

    # --- Preprocessing ----------------------------------------------------
    lowercase: bool = True
    remove_punctuation: bool = True
    stop_words: str | None = None  # None = keep all tokens

    # --- TF-IDF -----------------------------------------------------------
    min_df: float = 1
    max_df: float = 1.0
    max_features: int | None = None
    sublinear_tf: bool = False
    use_idf: bool = True
    norm: str = "l2"

    # ----------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Plain-dict representation for JSON serialization."""
        return asdict(self)

    def save(self, path: Path) -> None:
        """Write this config to *path* as JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)
