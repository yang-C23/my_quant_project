from __future__ import annotations

import numpy as np
import pandas as pd

from quant.research.ic import ic_decay, ic_report, quantile_returns, rank_ic


def _factor_frame(values: pd.DataFrame) -> pd.Series:
    values.index.name = "datetime"
    values.columns.name = "instrument"
    return values.stack().rename("factor")


def _prices_from_forward_returns(forward: pd.DataFrame) -> pd.DataFrame:
    dates = list(forward.index) + [forward.index[-1] + pd.Timedelta(days=1)]
    rows = []
    for instrument in forward.columns:
        for i, date in enumerate(dates):
            ret = float(forward.iloc[i - 1][instrument]) if i > 0 else 0.0
            rows.append(
                {
                    "instrument": instrument,
                    "date": date,
                    "open": 100.0,
                    "close": 100.0 * (1.0 + ret),
                }
            )
    return pd.DataFrame(rows)


def test_rank_ic_perfect_factor_is_one() -> None:
    dates = pd.date_range("2020-01-01", periods=6)
    instruments = ["A", "B", "C", "D"]
    values = pd.DataFrame([range(1, 5) for _ in dates], index=dates, columns=instruments)
    forward = values / 100.0

    got = rank_ic(_factor_frame(values), horizon=1, prices=_prices_from_forward_returns(forward))

    np.testing.assert_allclose(got["ic"].dropna(), 1.0)
    assert got.attrs["summary"]["mean"] == 1.0


def test_rank_ic_random_factor_is_near_zero() -> None:
    rng = np.random.default_rng(7)
    dates = pd.date_range("2020-01-01", periods=80)
    instruments = [f"S{i:02d}" for i in range(30)]
    factor = pd.DataFrame(rng.normal(size=(80, 30)), index=dates, columns=instruments)
    forward = pd.DataFrame(rng.normal(scale=0.01, size=(80, 30)), index=dates, columns=instruments)

    got = rank_ic(_factor_frame(factor), horizon=1, prices=_prices_from_forward_returns(forward))

    assert abs(got.attrs["summary"]["mean"]) < 0.08


def test_rank_ic_uses_next_open_not_same_day_close() -> None:
    dates = pd.to_datetime(["2020-01-01", "2020-01-02"])
    factor = _factor_frame(
        pd.DataFrame([[1.0, 2.0, 3.0]], index=dates[:1], columns=["A", "B", "C"])
    )
    prices = pd.DataFrame(
        {
            "instrument": ["A", "B", "C", "A", "B", "C"],
            "date": [dates[0]] * 3 + [dates[1]] * 3,
            "open": [100.0] * 6,
            "close": [101.0, 102.0, 103.0, 103.0, 102.0, 101.0],
        }
    )

    got = rank_ic(factor, horizon=1, prices=prices)

    assert got["ic"].iloc[0] == -1.0


def test_quantile_returns_are_monotonic_for_ordered_factor() -> None:
    dates = pd.date_range("2020-01-01", periods=4)
    instruments = [f"S{i}" for i in range(6)]
    values = pd.DataFrame([range(6) for _ in dates], index=dates, columns=instruments)
    forward = values / 100.0

    got = quantile_returns(
        _factor_frame(values), q=3, horizon=1, prices=_prices_from_forward_returns(forward)
    )
    mean_by_q = got.groupby("quantile")["mean_return"].mean()

    assert mean_by_q.loc[3] > mean_by_q.loc[2] > mean_by_q.loc[1]


def test_ic_decay_and_report_include_sample_distribution(tmp_path) -> None:
    dates = pd.date_range("2020-01-01", periods=5)
    instruments = ["A", "B", "C"]
    values = pd.DataFrame([range(3) for _ in dates], index=dates, columns=instruments)
    factor = _factor_frame(values)
    prices = _prices_from_forward_returns(values / 100.0)

    decay = ic_decay(factor, horizons=[1, 2], prices=prices)
    report = ic_report("demo", factor, output_dir=tmp_path, horizons=[1], prices=prices)

    assert decay["horizon"].tolist() == [1, 2]
    assert "Daily Sample Count Distribution" in report.read_text(encoding="utf-8")
