"""
Skeleton implementation of the proprietary “dual line breath” strategy.

Replace the placeholder logic with the actual indicator calculations and trade
rules. The class is intentionally minimal so you can focus on signal design.

Usage Example
-------------

.. code-block:: bash

    python backtest_engine.py --symbol 000001.SZ \\
        --strategy custom_strategies.dual_line_breath:DualLineBreathStrategy

"""

from __future__ import annotations

import backtrader as bt  # type: ignore[import]

__all__ = ["DualLineBreathStrategy"]


class DualLineBreathStrategy(bt.Strategy):
    """
    Placeholder for the dual-line breath rule set.

    Add your indicator definitions in :meth:`__init__` and implement order
    placement inside :meth:`next` or :meth:`next_open`.
    """

    params = dict()

    def __init__(self) -> None:
        # TODO: define custom indicators / data lines here.
        pass

    def next(self) -> None:
        raise NotImplementedError(
            "Implement the dual-line breath trading logic inside `next` or `next_open`."
        )
