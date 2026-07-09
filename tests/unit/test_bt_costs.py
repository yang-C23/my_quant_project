from __future__ import annotations

import pandas as pd
import pytest

from quant.backtest.costs import AShareCommission, AShareCosts


def test_side_cost_uses_literal_commission_minimum_stamp_and_transfer() -> None:
    costs = AShareCosts()

    # Buy 100 shares at 10: commission max(0.25, 5.00) + transfer 0.01 = 5.01.
    assert (
        costs.side_cost(price=10.0, size=100, is_sell=False, date=pd.Timestamp("2023-09-01"))
        == 5.01
    )
    # Sell 100 shares at 10: 5.00 commission + 0.01 transfer + 0.50 stamp = 5.51.
    assert (
        costs.side_cost(price=10.0, size=100, is_sell=True, date=pd.Timestamp("2023-09-01")) == 5.51
    )
    # Buy 1,000 shares at 100: 25.00 commission + 1.00 transfer = 26.00.
    assert (
        costs.side_cost(price=100.0, size=1000, is_sell=False, date=pd.Timestamp("2023-09-01"))
        == 26.0
    )
    # Sell: 25.00 commission + 1.00 transfer + 50.00 stamp = 76.00.
    assert (
        costs.side_cost(price=100.0, size=1000, is_sell=True, date=pd.Timestamp("2023-09-01"))
        == 76.0
    )


@pytest.mark.parametrize(
    ("date", "expected"),
    [
        ("2023-08-24", 0.001),
        ("2023-08-25", 0.001),
        ("2023-08-28", 0.0005),
        ("2023-08-29", 0.0005),
        ("2023-08-30", 0.0005),
    ],
)
def test_stamp_rate_switch_covers_two_days_each_side_and_cutover(
    date: str, expected: float
) -> None:
    assert AShareCosts().stamp_rate_at(pd.Timestamp(date)) == expected


def test_commission_bridge_uses_configured_settlement_date() -> None:
    commission = AShareCommission(AShareCosts())
    commission.set_trade_date(pd.Timestamp("2023-08-25"))

    # Pre-cutover sell of 100 at 10: 5.00 + 0.01 + 1.00 = 6.01.
    assert commission.getcommission(size=-100, price=10.0) == 6.01
