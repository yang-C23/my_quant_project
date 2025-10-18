"""
Factor evaluation utilities (IC / ICIR, etc.).

These helpers operate on pandas data frames / series, making them compatible
with both traditional pipeline output and Backtrader indicator exports.

Example
-------

.. code-block:: python

    import pandas as pd
    from factor_analysis import compute_ic

    factor = pd.Series([0.1, 0.2, -0.3], name="my_factor")
    fwd_ret = pd.Series([0.05, 0.01, -0.02], name="fwd_5d")
    ic = compute_ic(factor, fwd_ret)
    print(f"Spearman IC: {ic:.4f}")

"""

from __future__ import annotations

import pandas as pd


def compute_ic(factor: pd.Series, forward_returns: pd.Series) -> float:
    """Compute the Spearman rank IC between factor values and forward returns."""

    return factor.corr(forward_returns, method="spearman")
