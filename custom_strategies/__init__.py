"""
Namespace for Backtrader strategy implementations used across the project.

Strategies should expose a clear public API so they can be loaded dynamically
by :mod:`backtest_engine`. Refer to ``moving_average.py`` for an example.
"""

from .dual_line_breath import DualLineBreathStrategy
from .moving_average import MovingAverageCrossStrategy

__all__ = ["MovingAverageCrossStrategy", "DualLineBreathStrategy"]
