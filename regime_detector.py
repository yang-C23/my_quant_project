"""
Market regime detection utilities placeholder.

This module will encapsulate models or heuristics that classify different
market states to adapt strategies accordingly.
"""

from __future__ import annotations

import pandas as pd
from sklearn.cluster import KMeans


def detect_regimes(features: pd.DataFrame, n_regimes: int = 3) -> pd.Series:
    """Cluster market features into regimes using KMeans."""

    model = KMeans(n_clusters=n_regimes, n_init="auto", random_state=42)
    return pd.Series(model.fit_predict(features), index=features.index, name="regime")
