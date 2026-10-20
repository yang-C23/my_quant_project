"""NAV and action reconciliation must reject omitted distributions."""

import pandas as pd
import pytest

from quant.data.issuer_funds import reconcile_nav_actions, reviewed_nav_corrections


def test_cumulative_nav_checks_split_and_dividend_terms():
    dates = pd.date_range("2021-01-01", periods=4)
    nav = pd.DataFrame(
        {"date": dates, "unit_nav": [1, 1, 0.5, 0.4], "cumulative_nav": [1, 1, 1, 1]}
    )
    actions = pd.DataFrame(
        [
            {"kind": "split", "ex_date": dates[2], "ratio": 2},
            {"kind": "dividend", "ex_date": dates[3], "pay_date": dates[3], "per_share": 0.1},
        ]
    )
    assert reconcile_nav_actions(nav, actions)["ok"]
    assert not reconcile_nav_actions(nav, actions.iloc[:1])["ok"]
    actions.loc[1, "pay_date"] = pd.NaT
    with pytest.raises(ValueError, match="payment date"):
        reconcile_nav_actions(nav, actions)


def test_reviewed_exception_preserves_raw_and_rejects_changed_source():
    raw = pd.DataFrame({"date": ["2023-12-31"], "unit_nav": [0.9143], "cumulative_nav": [0.9143]})
    declaration = {
        "evidence": [{"sha256": "pinned_report"}],
        "nav_corrections": [
            {
                "date": "2023-12-31",
                "field": "cumulative_nav",
                "original": 0.9143,
                "verified_value": 1.8286,
                "evidence_sha256": "pinned_report",
                "reason": "annual report verifies cumulative growth",
            }
        ],
    }
    corrected = reviewed_nav_corrections(raw, declaration)
    assert raw.cumulative_nav.iloc[0] == 0.9143
    assert corrected.cumulative_nav.iloc[0] == 1.8286
    with pytest.raises(ValueError, match="no longer matches"):
        reviewed_nav_corrections(corrected, declaration)
