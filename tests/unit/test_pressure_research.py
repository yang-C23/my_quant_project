"""Observed missingness, publication delays and source units are financial semantics."""

import numpy as np
import pandas as pd
import pytest

from quant.data.pressure import parse_cboe_pressure, parse_sse_margin
from quant.longterm.pressure_research import lag_observations


def test_publication_lag_preserves_missing_latest_observation_and_future_invariance():
    calendar = pd.bdate_range("2020-01-02", periods=12)
    data = pd.DataFrame({"evidence": [1.0, np.nan, 3.0]}, index=calendar[[0, 2, 10]])
    full = lag_observations(data, calendar, lag=1, ttl=7)
    prefix = lag_observations(data.iloc[:2], calendar[:10], lag=1, ttl=7)
    pd.testing.assert_frame_equal(full.iloc[:10], prefix)
    assert pd.isna(full.iloc[0, 0])
    assert full.iloc[1, 0] == 1
    assert full.iloc[3:11, 0].isna().all()
    assert full.iloc[11, 0] == 3
    old = lag_observations(data.iloc[:1], calendar, lag=1, ttl=7)
    assert old.iloc[-3:, 0].isna().all()


def margin_document():
    return {
        "result": [
            {
                "opDate": "20200102",
                "rzye": 100,
                "rzmre": 5,
                "rzche": 4,
                "rqyl": 10,
                "rqylje": 50,
                "rqmcl": 3,
                "rzrqjyzl": 150,
            }
        ]
    }


def test_sse_margin_duplicates_and_units_are_checked():
    doc = margin_document()
    frame = parse_sse_margin([doc], "2026-10-20T00:00:00Z")
    assert frame.financing_balance_cny.iloc[0] == 100
    assert str(frame.borrowed_shares.dtype) == "Int64"
    with pytest.raises(ValueError, match="duplicated"):
        parse_sse_margin([doc, doc], "2026-10-20T00:00:00Z")
    doc["result"][0]["rzrqjyzl"] = 1510
    with pytest.raises(ValueError, match="reconcile"):
        parse_sse_margin([doc], "2026-10-20T00:00:00Z")


def test_cboe_counts_are_not_interpreted_as_index_levels():
    raw = b"title\nnotice\nDATE,CALLS,PUTS,TOTAL,P/C Ratio\n01/02/2020,300,200,500,0.67\n"
    frame = parse_cboe_pressure(raw, "total_putcall", "2026-10-20T00:00:00Z")
    assert frame.put_call_ratio.iloc[0] == 0.67
    with pytest.raises(ValueError, match="sum"):
        parse_cboe_pressure(raw.replace(b"500", b"501"), "total_putcall", "2026-10-20T00:00:00Z")
    with pytest.raises(ValueError, match="rounding"):
        parse_cboe_pressure(raw.replace(b"0.67", b"0.97"), "total_putcall", "2026-10-20T00:00:00Z")
