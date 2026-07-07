"""Research utilities for strategy analysis."""

from quant.research.forward_returns import EventStudyResult, run_event_study
from quant.research.ic import ic_decay, ic_report, quantile_returns, rank_ic

__all__ = [
    "EventStudyResult",
    "ic_decay",
    "ic_report",
    "quantile_returns",
    "rank_ic",
    "run_event_study",
]
