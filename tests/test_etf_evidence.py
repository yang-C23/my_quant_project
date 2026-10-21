"""Financial-unit, publication-time, missing-data and evidence-conflict checks."""

import json

import numpy as np
import pandas as pd
import pytest

from quant.longterm.etf_sources import (
    calendar_check,
    causal_total_return,
    chart_prices,
    combine_distribution_evidence,
    issuer_table_actions,
    ssga_actions,
)
from quant.longterm.vintage_valuation import archive_temperature, parse_shiller_vintage
from quant.longterm.cash_wait import liquidation_quote
from quant.longterm.ledger import Costs, dec


def test_split_only_prices_restore_old_units_without_duplicate_return(tmp_path):
    epochs = [946720800, 946807200, 946893600]  # exchange-local Jan 1, 2, 3 of 2000
    path = tmp_path / "chart.json"
    path.write_text(
        json.dumps(
            {
                "chart": {
                    "result": [
                        {
                            "meta": {"symbol": "T"},
                            "timestamp": epochs,
                            "indicators": {
                                "quote": [
                                    {
                                        "close": [50, 50, 51],
                                        "open": [50, 50, 51],
                                        "high": [50, 50, 51],
                                        "low": [50, 50, 51],
                                        "volume": [200, 200, 200],
                                    }
                                ]
                            },
                            "events": {
                                "splits": {
                                    "s": {"date": epochs[1], "numerator": 2, "denominator": 1}
                                }
                            },
                        }
                    ]
                }
            }
        )
    )
    bars, splits = chart_prices(path, "T", "2000-12-31")
    assert bars.close.tolist() == [100, 50, 51]
    assert bars.volume.tolist() == [100, 200, 200]
    signal = causal_total_return(bars, splits)
    assert signal.close.tolist() == [100, 100, 102]
    prefix = causal_total_return(bars.iloc[:1], splits.iloc[:0])
    pd.testing.assert_frame_equal(signal.iloc[:1], prefix, check_exact=True)


def test_missing_quote_cannot_be_forward_filled(tmp_path):
    path = tmp_path / "chart.json"
    path.write_text(
        json.dumps(
            {
                "chart": {
                    "result": [
                        {
                            "meta": {"symbol": "T"},
                            "timestamp": [946720800],
                            "indicators": {
                                "quote": [
                                    {
                                        "close": [None],
                                        "open": [1],
                                        "high": [1],
                                        "low": [1],
                                        "volume": [100],
                                    }
                                ]
                            },
                        }
                    ]
                }
            }
        )
    )
    with pytest.raises(ValueError, match="missing/invalid"):
        chart_prices(path, "T", "2000-12-31")


def test_issuer_precedence_emits_conflicts_not_silent_rounding(tmp_path):
    path = tmp_path / "issuer.txt"
    path.write_text("12/24/2018 | 12/26/2018 | 12/31/2018 | 0.42060\n")
    issuer = issuer_table_actions(path, "QQQ", "2019-01-01")
    exchange = issuer.assign(per_share=0.42061)
    result, conflicts = combine_distribution_evidence(issuer, exchange)
    assert result.per_share.iloc[0] == 0.42060
    assert len(conflicts) == 1
    path.write_text(path.read_text() + "12/24/2018 | 12/26/2018 | 12/31/2018 | 0.4\n")
    with pytest.raises(ValueError, match="duplicate"):
        issuer_table_actions(path, "QQQ", "2019-01-01")


def _vintage(name, release, earnings=1):
    dates = pd.date_range("1999-01-31", "2010-01-31", freq="ME")
    return pd.DataFrame(
        {
            "date": dates,
            "price": 10.0,
            "earnings": earnings,
            "available_at": pd.Timestamp(release),
            "vintage": name,
        }
    )


def test_archive_release_after_close_and_future_append_are_causal():
    old = _vintage("old", "2010-02-01T20:00:00Z")
    new = _vintage("new", "2010-02-02T21:01:00Z", 2)
    close = pd.Series([10.0, 10.0, 10.0], index=pd.date_range("2010-02-01", periods=3))
    result = archive_temperature(close, pd.concat([old, new]))
    assert result.vintage.tolist() == ["old", "old", "new"]
    assert result.pe.tolist() == [10, 10, 5]
    assert result.temperature.tolist() == [0.5, 0.5, 0.5]  # ties use midrank
    prefix = archive_temperature(close.iloc[:2], old)
    pd.testing.assert_frame_equal(result.iloc[:2], prefix, check_exact=True)


def test_early_exchange_close_cannot_use_later_same_day_archive():
    old = _vintage("old", "2010-11-25T20:00:00Z")
    new = _vintage("new", "2010-11-26T19:00:00Z", 2)
    dates = pd.to_datetime(["2010-11-26", "2010-11-29"])
    close = pd.Series([10.0, 10.0], index=dates)
    decisions = pd.Series(
        pd.to_datetime(["2010-11-26T18:00:00Z", "2010-11-29T21:00:00Z"]), index=dates
    )
    result = archive_temperature(
        close, pd.concat([old, new]), decision_times=decisions, maximum_age_days=400
    )
    assert result.vintage.tolist() == ["old", "new"]
    with pytest.raises(ValueError, match="closing timestamp missing"):
        archive_temperature(close, old, decision_times=decisions.iloc[:1])


def test_negative_latest_earnings_missing_history_and_staleness_fail_closed():
    source = _vintage("old", "2010-02-01T20:00:00Z")
    close = pd.Series([10.0, 10.0], index=pd.to_datetime(["2010-02-02", "2010-09-01"]))
    assert np.isnan(archive_temperature(close, source).temperature.iloc[-1])
    source.loc[source.index[-1], "earnings"] = -1
    assert archive_temperature(close, source).temperature.isna().all()
    short = _vintage("old", "2010-02-01T20:00:00Z").iloc[-90:]
    assert archive_temperature(close, short).temperature.isna().all()


def test_vintage_workbook_excludes_future_months_and_calendar_gaps_are_explicit(tmp_path):
    path = tmp_path / "vintage.xlsx"
    pd.DataFrame(
        [
            ["Title", None, None, None],
            ["Date", "P", "D", "E"],
            [2010.01, 10, 0.1, 1],
            [2010.02, 11, 0.1, 2],
        ]
    ).to_excel(path, header=False, index=False)
    result = parse_shiller_vintage(path, "2010-02-15T20:00:00Z")
    assert result.date.tolist() == [pd.Timestamp("2010-01-31")]
    dates = pd.bdate_range("2010-02-01", periods=3)
    check = calendar_check(pd.DataFrame({"close": [1, 1]}, index=dates[[0, 2]]), dates)
    assert check == {"missing": ["2010-02-02"], "unexpected": []}


def test_cash_fund_liquidation_does_not_spend_dividend_receivables():
    last = pd.Series({"shares": 10, "cash": 1.25, "receivable": 2.50})
    costs = Costs(commission_rate=dec("0.001"), slippage_bps=dec("10"))
    quote = liquidation_quote(last, 100, costs)
    # 10*100*.999 = 999; fee=.999 rounded to 1.00. Receivable stays outside cash.
    assert quote["cash_after_sale_settlement"] == 999.25
    assert quote["wealth_net_liquidation"] == 1001.75
    assert quote["unpaid_dividend_receivable"] == 2.5
    with pytest.raises(ValueError, match="cash-in-lieu"):
        liquidation_quote(
            pd.Series({"shares": 10.5, "cash": 1.25, "receivable": 2.5}),
            100,
            costs,
        )


def test_issuer_invalid_pay_date_blocks_history_and_zero_is_not_missing(tmp_path):
    path = tmp_path / "distributions.xlsx"
    pd.DataFrame(
        {
            "TICKER": ["T", "T", "T"],
            "EX-DATE": ["2008-03-03", "2008-04-01", "2008-05-01"],
            "PAYABLE DATE": ["2008-02-11", "2008-04-09", "2008-05-09"],
            "DIVIDEND ($)": [0.1, 0, 0.2],
            "SHORT TERM CAPITAL GAIN ($)": [np.nan, np.nan, 0.01],
            "LONG TERM CAPITAL GAIN ($)": [np.nan, np.nan, 0.02],
        }
    ).to_excel(path, sheet_name="dividend", index=False)
    with pytest.raises(ValueError, match="unverified"):
        ssga_actions(path, "T", "2008-12-31")
    allowed = ssga_actions(path, "T", "2008-12-31", start="2008-04-01")
    assert allowed.per_share.tolist() == [0, 0.23]
    assert allowed.ex_date.min() == pd.Timestamp("2008-04-01")
