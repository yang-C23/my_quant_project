"""Causal monthly evidence and end-to-end saved cash-pool accounting."""

from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant.config import load_config
from quant.data.snapshots import write_json
from quant.longterm.pool_data import periodic_percentile, shiller_temperature
from quant.longterm.features import align_available
from quant.longterm.pool_registry import pool_registry, pool_windows
from quant.longterm.pool_research import _run_asset, make_pool_report
from quant.longterm.stages import StageSpec


ROOT = Path(__file__).resolve().parents[2]


def test_arrow_microsecond_publications_align_to_nanosecond_decisions(tmp_path):
    observations = pd.DataFrame(
        {
            "date": pd.to_datetime(["2020-01-02"]),
            "available_at": pd.Series(pd.to_datetime(["2020-01-02 22:00Z"])).astype(
                "datetime64[us, UTC]"
            ),
            "value": [10.0],
        }
    )
    path = tmp_path / "arrow.parquet"
    observations.to_parquet(path)
    restored = pd.read_parquet(path)
    decisions = pd.to_datetime(["2020-01-02 21:00Z", "2020-01-03 21:00Z"])
    result = align_available(restored, decisions, "value")
    assert pd.isna(result.iloc[0])
    assert result.iloc[1] == 10.0


def test_registry_has_all_stages_exits_and_no_duplicate_identifiers():
    config = load_config(ROOT / "configs/cash_pool.yaml")
    registry = pool_registry(config)
    assert len({x["id"] for x in registry}) == len(registry)
    entries = {x["policy"]["entry"] for x in registry}
    assert {"value_pressure", "value_stabilized", "value_relief", "valuation"} <= entries
    assert {0, 0.25, 0.5} <= {x["policy"]["core_fraction"] for x in registry}
    assert {3, 6, 12} <= {x["policy"]["tranches"] for x in registry}
    assert {1, 2, 3} <= {x["policy"]["event_tranches"] for x in registry}
    assert {6, 12} == {
        x["observation_lag_months"]
        for x in registry
        if x.get("valuation_source") == "shiller_proxy"
    }


def test_factor_regime_gap_preserves_five_year_account_and_monthly_funding():
    config = load_config(ROOT / "configs/cash_pool.yaml")
    calendar = pd.bdate_range("2011-01-03", "2019-10-11")
    available = calendar[(calendar < "2012-06-01") | (calendar >= "2017-06-01")]
    windows = pool_windows(available, config, calendar=calendar)
    five = next(window for window in windows if window["id"] == "latest_5y")
    assert five["start"] == "2014-10-13"
    assert five["end"] == "2019-10-11"
    # Every monthly contribution belongs to the same five-year account,
    # including 32 months before the factor becomes ready again.
    dates = calendar[(calendar >= five["start"]) & (calendar <= five["end"])]
    months = dates.to_period("M").unique()
    assert len(months) == 61
    assert len(months[months < pd.Period("2017-06", freq="M")]) == 32
    split = next(window for window in windows if window["id"] == "retrospective_validation")
    assert pd.Timestamp(split["start"]) < pd.Timestamp("2017-06-01")
    with pytest.raises(ValueError, match="full trading calendar"):
        pool_windows(available, config)


def test_full_trading_calendar_does_not_change_continuous_factor_windows():
    config = load_config(ROOT / "configs/cash_pool.yaml")
    calendar = pd.bdate_range("2005-01-03", "2026-10-19")
    available = calendar[260:-5]
    assert pool_windows(available, config) == pool_windows(available, config, calendar=calendar)


def test_monthly_percentile_has_full_calendar_warmup_and_excludes_current():
    dates = pd.date_range("2010-01-31", periods=80, freq="ME")
    values = pd.Series(np.arange(1, 81, dtype=float), index=dates)
    values.iloc[60] = 30
    ranked = periodic_percentile(values, years=5, frequency=12)
    assert ranked.iloc[:60].isna().all()
    assert ranked.iloc[60] == pytest.approx((29 + 0.5) / 60)
    pd.testing.assert_series_equal(
        periodic_percentile(values.iloc[:70], years=5, frequency=12),
        ranked.iloc[:70],
    )


def test_revised_monthly_proxy_stops_at_vintage_expiry():
    config = load_config(ROOT / "configs/cash_pool.yaml")
    dates = pd.date_range("2000-01-31", periods=160, freq="ME")
    observed = pd.DataFrame({"date": dates, "pe_latest_vintage": np.arange(1, 161)})
    bars = pd.DataFrame(
        {"close": 100.0},
        index=pd.bdate_range("2013-01-01", "2015-12-31"),
    )
    rank = shiller_temperature(bars, observed, "pe", 10, 6, config)
    assert rank.loc["2013-02"].notna().all()
    assert rank.loc["2015"].isna().all()
    changed = pd.concat(
        [
            observed,
            pd.DataFrame({"date": [pd.Timestamp("2015-12-31")], "pe_latest_vintage": [0.1]}),
        ],
        ignore_index=True,
    )
    pd.testing.assert_series_equal(
        rank.loc[:"2014-01-01"],
        shiller_temperature(bars, changed, "pe", 10, 6, config).loc[:"2014-01-01"],
    )


def test_saved_asset_study_reconstructs_cash_and_resumes_without_new_trades(tmp_path):
    config = load_config(ROOT / "configs/cash_pool.yaml")
    registry = [
        x
        for x in pool_registry(config)
        if x["id"] in {"pool_unconditional_core0", "pool_stabilized_core0", "legacy_dca"}
    ]
    dates = pd.bdate_range("2010-01-01", periods=800)
    close = np.r_[100 + np.sin(np.arange(270)), np.linspace(98, 65, 10), np.linspace(65, 100, 520)]
    bars = pd.DataFrame({"close": close}, index=dates)
    root = tmp_path / "study"
    (root / "inputs").mkdir(parents=True)
    bars.to_parquet(root / "inputs" / "fixture.parquet")
    registration = {"config": config, "catalog_versions": {}, "experiments": registry}
    write_json(root / "registration.json", registration)
    asset = {"id": "fixture", "index": "fixture", "market": "CN", "name": "fixture"}
    evidence = {"basis": "price_only"}
    job = {"directory": str(root), "data_root": str(tmp_path), "asset": asset, "evidence": evidence}
    first = _run_asset(job)
    table = pd.read_parquet(root / "fixture" / "results.parquet")
    assert set(table.status) == {"computed"}, table.get("reason")
    assert table.independent_ledger_verified.all()
    assert table.result_directory.str.startswith("fixture/").all()
    assert not table.result_directory.str.contains(str(tmp_path), regex=False).any()
    assert first == _run_asset(job)
    pd.testing.assert_frame_equal(table, pd.read_parquet(root / "fixture" / "results.parquet"))
    make_pool_report(
        root, table, [{"asset": "fixture"}], {"experiments": 3, "statuses": first["statuses"]}
    )
    assert (root / "report.md").exists()
    assert asdict(StageSpec())["volatility_lag"] == 5
