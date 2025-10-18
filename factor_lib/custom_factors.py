"""
Custom factor implementations for the project.

Currently provides a stub for the Dual Line Breath factor that can be
expanded once the research specification is finalized.
"""

from __future__ import annotations

import pandas as pd


class DualLineBreathIndicator:
    """
    Placeholder implementation for the \"dual line breath\" factor.

    Parameters
    ----------
    short_window : int
        Lookback window for the short-term average.
    long_window : int
        Lookback window for the long-term average.
    """

    def __init__(self, short_window: int = 5, long_window: int = 20) -> None:
        self.short_window = short_window
        self.long_window = long_window

    def compute(self, data: pd.DataFrame) -> pd.Series:
        """
        Compute the factor values on OHLCV data.

        Parameters
        ----------
        data : pd.DataFrame
            Data frame containing at least a \"close\" price column.

        Returns
        -------
        pd.Series
            Series representing the factor values.
        """

        closes = data["close"].astype(float)
        short_ma = closes.rolling(self.short_window, min_periods=1).mean()
        long_ma = closes.rolling(self.long_window, min_periods=1).mean()
        return short_ma - long_ma
