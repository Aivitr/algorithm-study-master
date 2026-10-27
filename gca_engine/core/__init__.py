"""GCA 六指标数学核心（从 ami_parser 迁移，数学公式与旧基线保持一致）。"""

from gca_engine.core.config import GCAConfig, ZERO_EPS
from gca_engine.core.metrics import GCAResult, compute_gca_metrics

__all__ = ["GCAConfig", "GCAResult", "compute_gca_metrics", "ZERO_EPS"]
