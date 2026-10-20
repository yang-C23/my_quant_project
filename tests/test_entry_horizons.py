"""Calendar maturity, actual cash flows, threshold boundaries and prefix equality."""

from dataclasses import asdict

import pandas as pd
import pytest

from quant.longterm.cash_pool import PoolPolicy, run_cash_pool
from quant.longterm.entry_horizons import (
    accumulated_cash,
    annual_origins,
    horizon_end,
    first_fill,
    post_entry_metrics,
)
from quant.longterm.ledger import Costs, dec


def test_calendar_horizon_needs_full_anniversary_and_next_session():
    dates = pd.bdate_range("2015-01-02", "2025-01-06")
    assert horizon_end(dates, pd.Timestamp("2015-01-03"), 10) == (
        pd.Timestamp("2025-01-03"),
        "complete",
    )
    assert horizon_end(dates[:-2], pd.Timestamp("2015-01-03"), 10)[1] == "right_censored"
    assert horizon_end(dates, pd.Timestamp("2020-01-04"), 5)[0] == pd.Timestamp("2025-01-06")
    assert horizon_end(dates, None, 5)[1] == "no_entry"


def test_origins_keep_first_partial_eligible_year():
    dates = pd.bdate_range("2019-07-01", "2022-01-10")
    origins = annual_origins(dates)
    assert origins[0] == dates[252]
    assert origins[1:] == [pd.Timestamp("2021-01-01"), pd.Timestamp("2022-01-03")]


def test_cash_accumulation_and_strict_valuation_boundary():
    dates = pd.bdate_range("2020-01-01", periods=5)
    bars = pd.DataFrame({"close": [10.0] * 5}, index=dates)
    features = pd.DataFrame({"temperature": [0.4, 0.40001, 0.39999, 0.2, 0.1]}, index=dates)
    assert first_fill(bars, features, PoolPolicy(exit="none"), dates[0]) == dates[3]
    assert (
        accumulated_cash(
            pd.Timestamp("2019-12-31"),
            pd.Timestamp("2020-02-03"),
            {"initial": 100000, "monthly": 1000},
        )
        == 102000
    )


def test_post_entry_measurement_excludes_wait_and_retains_first_fee():
    dates = pd.bdate_range("2020-01-01", "2021-03-01")
    bars = pd.DataFrame({"close": 10.0}, index=dates)
    features = pd.DataFrame({"temperature": 1.0}, index=dates)
    features.loc["2020-06-01":, "temperature"] = 0.1
    policy = PoolPolicy(entry="valuation", exit="none", tranches=1)
    costs = Costs(commission_rate=dec(0.001), slippage_bps=dec(0))
    result = run_cash_pool(bars, features, policy, symbol="T", execution="next_close", costs=costs)
    entry = pd.Timestamp(result.metrics["first_tactical_buy"])
    post = post_entry_metrics(result.daily, result.journal, entry)
    assert entry == pd.Timestamp("2020-06-02")
    assert post["post_twr"] < 0  # first trade's fee cannot disappear in rebasing
    assert post["post_principal_loss_at_end"]
    assert post["post_contributed"] == result.metrics["contributed"]
    assert post["post_start"] == "2020-06-02"
    # Combining waiting cash into one entry deposit must preserve all later fills.
    initial = accumulated_cash(dates[0], entry, asdict(policy))
    matched = run_cash_pool(
        bars,
        features,
        PoolPolicy(**(asdict(policy) | {"initial": initial})),
        symbol="T",
        start=entry,
        execution="next_close",
        costs=costs,
    )
    assert matched.daily.equity.iloc[-1] == result.daily.equity.iloc[-1]
    a = result.journal[result.journal.kind.eq("buy")].reset_index(drop=True)
    b = matched.journal[matched.journal.kind.eq("buy")].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b, check_exact=True)
    assert post["post_twr"] == pytest.approx(matched.metrics["twr"], abs=1e-14)
