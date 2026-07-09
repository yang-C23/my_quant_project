from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant.backtest import qlib_topk
from quant.backtest.qlib_topk import (
    ExchangeConfig,
    TopkConfig,
    build_exchange_kwargs,
    build_score_series,
    extract_metrics,
    factor_frame_to_series,
    load_topk_config,
    parse_topk_config,
    signal_frame_to_series,
)
from quant.signals.factors import factor_mom_20, factor_names


def _baseline_raw() -> dict:
    return {
        "name": "topk_baseline",
        "kind": "factor",
        "score": "mom_20",
        "start": "2015-01-01",
        "end": "2021-12-31",
        "universe": {"source": "list_symbols", "exclude_boards": ["star", "b"], "at": None},
        "topk": 50,
        "n_drop": 5,
        "benchmark": "sh000001",
        "exchange": {
            "open_cost": 0.0005,
            "close_cost": 0.0015,
            "min_cost": 5,
            "limit_threshold": 0.095,
        },
    }


def test_baseline_config_matches_task_defaults() -> None:
    cfg = load_topk_config(Path("configs/backtest/topk_baseline.yaml"))

    assert cfg.name == "topk_baseline"
    assert cfg.kind == "factor"
    assert cfg.score == "mom_20"
    assert cfg.start == "2015-01-01"
    assert cfg.end == "2021-12-31"
    assert cfg.universe.source == "list_symbols"
    assert cfg.universe.exclude_boards == ("star", "b")
    assert cfg.universe.at is None
    assert cfg.topk == 50
    assert cfg.n_drop == 5
    assert cfg.benchmark == "sh000001"
    assert build_exchange_kwargs(cfg) == {
        "open_cost": 0.0005,
        "close_cost": 0.0015,
        "min_cost": 5.0,
        "limit_threshold": 0.095,
    }


def test_parse_topk_config_validates_schema() -> None:
    cfg = parse_topk_config(_baseline_raw())

    assert cfg.exchange == ExchangeConfig(
        open_cost=0.0005,
        close_cost=0.0015,
        min_cost=5.0,
        limit_threshold=0.095,
    )

    invalid = _baseline_raw() | {"n_drop": 51}
    with pytest.raises(ValueError, match="n_drop"):
        parse_topk_config(invalid)

    invalid = _baseline_raw() | {"kind": "model"}
    with pytest.raises(ValueError, match="kind"):
        parse_topk_config(invalid)


def test_signal_frame_to_series_encodes_binary_scores() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["sh600000", "sz000001", "sh600000"],
            "date": ["2020-01-03", "2020-01-02", "2020-01-02"],
            "sig": [True, False, 1],
        }
    )

    score = signal_frame_to_series(frame, "entry_signal")

    assert score.name == "entry_signal"
    assert score.index.names == ["datetime", "instrument"]
    assert score.loc[(pd.Timestamp("2020-01-02"), "SH600000")] == 1.0
    assert score.loc[(pd.Timestamp("2020-01-02"), "SZ000001")] == 0.0
    assert set(score.to_numpy()) <= {0.0, 1.0}
    assert score.index.is_monotonic_increasing


def test_factor_frame_to_series_preserves_float_scores_and_drops_nan() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["sh600000", "sz000001", "sh600000"],
            "date": ["2020-01-03", "2020-01-02", "2020-01-02"],
            "factor": [0.25, -0.1, np.nan],
        }
    )

    score = factor_frame_to_series(frame, "mom_20")

    assert score.name == "mom_20"
    assert score.index.names == ["datetime", "instrument"]
    assert score.loc[(pd.Timestamp("2020-01-02"), "SZ000001")] == pytest.approx(-0.1)
    assert score.loc[(pd.Timestamp("2020-01-03"), "SH600000")] == pytest.approx(0.25)
    assert len(score) == 2


def test_build_score_series_factor_uses_compute_factor_frame(monkeypatch) -> None:
    calls: list[tuple[str, tuple[str, ...], str, str]] = []

    def fake_compute_factor_frame(
        name: str,
        symbols: list[str],
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        calls.append((name, tuple(symbols), str(start), str(end)))
        return pd.DataFrame({"symbol": ["sh600000"], "date": ["2020-01-02"], "factor": [0.3]})

    monkeypatch.setattr(qlib_topk, "compute_factor_frame", fake_compute_factor_frame)
    cfg = TopkConfig(
        name="test",
        kind="factor",
        score="mom_20",
        start="2020-01-01",
        end="2020-01-31",
    )

    score = build_score_series(cfg, ["sh600000"])

    assert calls == [("mom_20", ("sh600000",), "2020-01-01", "2020-01-31")]
    assert score.loc[(pd.Timestamp("2020-01-02"), "SH600000")] == pytest.approx(0.3)


def test_build_score_series_signal_uses_to_factor(monkeypatch) -> None:
    expected = pd.Series(
        [1.0],
        index=pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2020-01-02"), "SH600000")], names=["datetime", "instrument"]
        ),
        name="entry_signal",
    )
    calls: list[tuple[str, tuple[str, ...], str, str]] = []

    def fake_to_factor(
        name: str,
        symbols: list[str],
        start: str | None = None,
        end: str | None = None,
    ) -> pd.Series:
        calls.append((name, tuple(symbols), str(start), str(end)))
        return expected

    monkeypatch.setattr(qlib_topk, "to_factor", fake_to_factor)
    cfg = TopkConfig(
        name="test",
        kind="signal",
        score="entry_signal",
        start="2020-01-01",
        end="2020-01-31",
    )

    score = build_score_series(cfg, ["sh600000"])

    assert calls == [("entry_signal", ("sh600000",), "2020-01-01", "2020-01-31")]
    pd.testing.assert_series_equal(score, expected)


def test_extract_metrics_uses_qlib_report_columns() -> None:
    report = pd.DataFrame(
        {
            "return": [0.01, -0.02, 0.015, 0.004],
            "bench": [0.002, -0.01, 0.006, -0.001],
            "cost": [0.001, 0.0005, 0.0015, 0.0],
            "turnover": [0.2, 0.1, 0.3, 0.0],
        },
        index=pd.date_range("2020-01-01", periods=4),
    )

    metrics = extract_metrics(report)

    assert set(metrics) == {
        "annualized_return",
        "information_ratio",
        "max_drawdown",
        "turnover_mean",
        "excess_return_wo_cost",
        "excess_return_with_cost",
    }
    assert metrics["turnover_mean"] == pytest.approx(0.15)
    assert all(np.isfinite(value) for value in metrics.values())


def test_mom_20_registered_and_tail_perturbation_does_not_change_history() -> None:
    assert "mom_20" in factor_names()
    base_df = pd.DataFrame({"close": np.arange(1.0, 31.0)})
    changed_df = base_df.copy()
    changed_df.loc[29, "close"] = 1000.0

    base = factor_mom_20(base_df)
    changed = factor_mom_20(changed_df)

    pd.testing.assert_series_equal(base.iloc[:-1], changed.iloc[:-1])
    assert base.iloc[20] == pytest.approx(20.0)


def _regime_raw() -> dict:
    raw = _baseline_raw()
    raw["name"] = "topk_amv_switch"
    raw["regime"] = {
        "kind": "amv_immediate",
        "index": "sh999999",
        "k": 2.13,
        "buy_th": 4.0,
        "sell_th": -2.3,
    }
    return raw


def _overlay_inputs() -> tuple[pd.DataFrame, pd.Series, pd.DatetimeIndex]:
    dates = pd.date_range("2020-01-01", periods=5)
    report = pd.DataFrame(
        {
            "return": [0.10, 0.20, -0.10, 0.05, 0.30],
            "bench": [0.0, 0.0, 0.0, 0.0, 0.0],
            "cost": [0.01, 0.02, 0.03, 0.04, 0.05],
            "turnover": [0.1, 0.2, 0.3, 0.4, 0.5],
        },
        index=dates,
    )
    regime = pd.Series([0, 1, 1, 0, 1], index=dates)
    return report, regime, dates


def test_apply_regime_overlay_uses_tplus1_position_and_switch_costs() -> None:
    report, regime, _dates = _overlay_inputs()

    got = qlib_topk.apply_regime_overlay(
        report,
        regime,
        open_cost=0.001,
        close_cost=0.002,
    )

    assert list(got["position"]) == [0.0, 0.0, 1.0, 1.0, 0.0]
    assert list(got["overlay_return"]) == pytest.approx([0.0, 0.0, -0.10, 0.05, 0.0])
    assert list(got["overlay_cost"]) == pytest.approx([0.0, 0.0, 0.031, 0.04, 0.002])


def test_apply_regime_overlay_shift_delays_same_day_flips() -> None:
    report, regime, dates = _overlay_inputs()

    got = qlib_topk.apply_regime_overlay(
        report,
        regime,
        open_cost=0.001,
        close_cost=0.002,
    )

    assert got.loc[dates[1], "position"] == 0.0
    assert got.loc[dates[2], "position"] == 1.0
    assert got.loc[dates[3], "position"] == 1.0
    assert got.loc[dates[4], "position"] == 0.0


def test_parse_topk_config_without_regime_keeps_baseline_shape() -> None:
    cfg = parse_topk_config(_baseline_raw())

    assert cfg.regime is None
    assert cfg.name == "topk_baseline"
    assert cfg.score == "mom_20"


def test_parse_topk_config_validates_regime_schema() -> None:
    cfg = parse_topk_config(_regime_raw())

    assert cfg.regime == qlib_topk.RegimeConfig(
        kind="amv_immediate",
        index="sh999999",
        k=2.13,
        buy_th=4.0,
        sell_th=-2.3,
    )

    invalid = _regime_raw()
    invalid["regime"]["kind"] = "confirm_life"
    with pytest.raises(ValueError, match="regime.kind"):
        parse_topk_config(invalid)

    missing = _regime_raw()
    del missing["regime"]["sell_th"]
    with pytest.raises(ValueError, match="regime.sell_th"):
        parse_topk_config(missing)


def test_amv_switch_config_matches_task_defaults() -> None:
    cfg = load_topk_config(Path("configs/backtest/topk_amv_switch.yaml"))

    assert cfg.name == "topk_amv_switch"
    assert cfg.kind == "factor"
    assert cfg.score == "mom_20"
    assert cfg.start == "2015-01-01"
    assert cfg.end == "2021-12-31"
    assert cfg.universe.exclude_boards == ("star", "b")
    assert cfg.topk == 50
    assert cfg.n_drop == 5
    assert cfg.benchmark == "sh000001"
    assert build_exchange_kwargs(cfg) == {
        "open_cost": 0.0005,
        "close_cost": 0.0015,
        "min_cost": 5.0,
        "limit_threshold": 0.095,
    }
    assert cfg.regime == qlib_topk.RegimeConfig(
        kind="amv_immediate",
        index="sh999999",
        k=2.13,
        buy_th=4.0,
        sell_th=-2.3,
    )
