from __future__ import annotations

from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant.research.optimize import (
    IS_END_LIMIT,
    ResearchConfig,
    neighborhood_stability,
    run_param_scan,
    sample_symbols,
    write_scan_report,
)


def _prices(symbol: str, start: str | None, end: str | None) -> pd.DataFrame:
    del start, end
    dates = pd.date_range("2020-01-01", periods=9, freq="D")
    close = [100.0, 100.0, 110.0, 100.0, 95.0, 100.0, 100.0, 100.0, 100.0]
    return pd.DataFrame(
        {
            "symbol": symbol,
            "date": dates,
            "open": [100.0] * len(dates),
            "high": [111.0] * len(dates),
            "low": [94.0] * len(dates),
            "close": close,
            "volume": [1_000.0] * len(dates),
            "amount": [100_000.0] * len(dates),
            "raw_open": [100.0] * len(dates),
            "is_suspended": [False] * len(dates),
            "limit_up_price": [np.nan] * len(dates),
        }
    )


def _signal_builder(name: str, bars: pd.DataFrame, params: dict) -> pd.Series:
    assert name == "synthetic"
    threshold = int(params["threshold"])
    dates = {
        2: pd.Timestamp("2020-01-01"),
        1: pd.Timestamp("2020-01-03"),
        0: pd.Timestamp("2020-01-05"),
    }
    return pd.Series(pd.to_datetime(bars["date"]).eq(dates[threshold]).to_numpy(), index=bars.index)


def test_param_scan_sorts_known_best_and_loads_each_symbol_once(tmp_path: Path) -> None:
    calls: Counter[str] = Counter()

    def loader(symbol: str, start: str | None, end: str | None) -> pd.DataFrame:
        calls[symbol] += 1
        return _prices(symbol, start, end)

    cfg = ResearchConfig(
        name="synthetic_scan",
        signal="synthetic",
        symbols=("sh600000", "sz000001"),
        grid={"threshold": (0, 1, 2)},
        baseline={"threshold": 1},
        is_start="2020-01-01",
        is_end="2020-01-09",
        horizons=(1,),
        objective="h1_avg",
        min_signals_per_year=0,
    )

    result = run_param_scan(cfg, price_loader=loader, signal_builder=_signal_builder)
    paths = write_scan_report(result, tmp_path, cfg.name)

    assert result.top.iloc[0]["threshold"] == 2
    assert result.top.iloc[0]["h1_avg"] == pytest.approx(0.10)
    assert result.baseline["threshold"] == 1
    assert calls == {"sh600000": 1, "sz000001": 1}
    assert paths["csv"].exists()
    assert "Top 5" in paths["md"].read_text(encoding="utf-8")


def test_neighborhood_stability_rejects_cliff_point() -> None:
    table = pd.DataFrame(
        {
            "x": [0, 1, 2, 3, 4],
            "h5_avg": [0.03, 0.02, 0.30, 0.01, 0.02],
        }
    )

    got = neighborhood_stability(
        table,
        {"x": [0, 1, 2, 3, 4]},
        table.loc[2],
        metric="h5_avg",
        baseline_value=0.015,
    )

    assert got["x"].tolist() == [1, 3]
    assert got.attrs["stable"] is False


def test_neighborhood_stability_accepts_flat_peak() -> None:
    table = pd.DataFrame(
        {
            "x": [0, 1, 2, 3, 4],
            "h5_avg": [0.01, 0.08, 0.10, 0.09, 0.01],
        }
    )

    got = neighborhood_stability(
        table,
        {"x": [0, 1, 2, 3, 4]},
        table.loc[2],
        metric="h5_avg",
        baseline_value=0.02,
    )

    assert got.attrs["stable"] is True


def test_config_rejects_is_end_beyond_bound() -> None:
    blocked_end = (IS_END_LIMIT + pd.Timedelta(days=1)).date().isoformat()

    with pytest.raises(ValueError, match="IS end"):
        ResearchConfig.from_mapping(
            {
                "signal": "kdj_oversold",
                "grid": {"j_threshold": [13]},
                "baseline": {"j_threshold": 13},
                "is_end": blocked_end,
            }
        )


def test_sample_symbols_is_deterministic_and_unbiased() -> None:
    universe = (
        [f"bj{i:06d}" for i in range(300)]
        + [f"sh{i:06d}" for i in range(300)]
        + [f"sz{i:06d}" for i in range(300)]
    )

    got = sample_symbols(universe, 300, seed=42)
    again = sample_symbols(universe, 300, seed=42)

    assert got == again
    assert len(got) == 300
    # 头部截断会得到 300 个 bj；随机抽样必须混合三个交易所
    prefixes = {sym[:2] for sym in got}
    assert prefixes == {"bj", "sh", "sz"}
    assert sample_symbols(universe, None) == universe
    assert sample_symbols(universe, 10_000) == universe
