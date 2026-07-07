from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import pandas as pd

_SPEC = spec_from_file_location(
    "validate_vs_pg", Path(__file__).resolve().parents[2] / "scripts" / "validate_vs_pg.py"
)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

compare_hfq = _MODULE.compare_hfq
compare_raw_ohlcv = _MODULE.compare_raw_ohlcv
compare_row_counts = _MODULE.compare_row_counts
truncate_to_common_window = _MODULE.truncate_to_common_window


def _daily() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["sh600000", "sh600000", "sz000001"],
            "date": pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-04"]),
            "open": [10.0, 10.5, 20.0],
            "high": [10.8, 10.7, 20.5],
            "low": [9.9, 10.2, 19.8],
            "close": [10.4, 10.3, 20.2],
            "volume": [1000, 1100, 2000],
            "amount": [10_000.0, 11_000.0, 40_000.0],
        }
    )


def _adjust() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["sh600000", "sh600000", "sz000001"],
            "date": pd.to_datetime(["2021-01-04", "2021-01-05", "2021-01-04"]),
            "hfq_factor": [1.0, 1.1, 2.0],
        }
    )


def test_compare_raw_ohlcv_detects_close_change_as_c4() -> None:
    v2 = _daily()
    pg = _daily()
    pg.loc[1, "close"] += 0.01

    result = compare_raw_ohlcv(v2, pg)

    assert result.status == "FAIL"
    assert result.issues[0].check == "C4"
    assert result.issues[0].column == "close"


def test_compare_row_counts_detects_deleted_row_as_c3() -> None:
    v2 = _daily()
    pg = _daily().iloc[:-1]

    result = compare_row_counts(v2, pg)

    assert result.status == "FAIL"
    assert result.issues[0].check == "C3"
    assert result.issues[0].column == "row_count"


def test_compare_hfq_detects_factor_perturbation_as_c5() -> None:
    v2_daily = _daily()
    pg_daily = _daily()
    v2_adjust = _adjust()
    pg_adjust = _adjust()
    pg_adjust.loc[1, "hfq_factor"] *= 1.0001

    hard, view = compare_hfq(v2_daily, v2_adjust, pg_daily, pg_adjust)

    assert view is None
    assert hard.status == "FAIL"
    assert {issue.column for issue in hard.issues} == {"hfq_factor", "hfq_close_recalc"}


def test_compare_hfq_view_is_warning_band_only() -> None:
    daily = _daily()
    adjust = _adjust()
    view = daily[["symbol", "date", "close"]].copy()
    view["close"] = daily["close"] * adjust["hfq_factor"]
    view.loc[1, "close"] = view.loc[1, "close"].round(2) + 0.01

    hard, view_result = compare_hfq(daily, adjust, daily, adjust, pg_hfq_view=view)

    assert hard.status == "PASS"
    assert view_result is not None
    assert view_result.status == "WARN"


def test_truncate_to_common_window_uses_min_max_date() -> None:
    v2 = _daily()
    pg = pd.concat(
        [
            _daily(),
            pd.DataFrame(
                {
                    "symbol": ["sh600000"],
                    "date": [pd.Timestamp("2021-01-06")],
                    "open": [1.0],
                    "high": [1.0],
                    "low": [1.0],
                    "close": [1.0],
                    "volume": [1],
                    "amount": [1.0],
                }
            ),
        ],
        ignore_index=True,
    )

    v2_out, pg_out, max_date = truncate_to_common_window(v2, pg)

    assert max_date == pd.Timestamp("2021-01-05")
    assert pd.to_datetime(v2_out["date"]).max() == max_date
    assert pd.to_datetime(pg_out["date"]).max() == max_date
