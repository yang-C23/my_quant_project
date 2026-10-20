"""A current valuation must react to today's price without using unreleased EPS."""

from pathlib import Path
import json

import numpy as np
import pandas as pd
import pytest

from quant.config import load_config
from quant.data.catalog import DataCatalog
from quant.data.snapshots import write_json
from quant.longterm.current_pe import current_pe_registry, current_pe_temperature
from quant.longterm.pool_research import _run_asset

ROOT = Path(__file__).resolve().parents[2]


def monthly():
    return pd.DataFrame(
        {
            "date": pd.date_range("2010-01-31", "2024-12-31", freq="ME"),
            "monthly_average_price": 100.0,
            "interpolated_earnings_12m": 5.0,
        }
    )


def config():
    return load_config(ROOT / "configs/current_price_pe.yaml") | {
        "first_comparable_month": "2010-01-31"
    }


def test_current_numerator_moves_now_but_future_months_cannot_rewrite_it():
    dates = pd.to_datetime(["2023-01-03", "2023-01-04", "2023-01-05"])
    prices = pd.Series([100.0, 50.0, 60.0], index=dates)
    source = monthly()
    result, reference = current_pe_temperature(prices, source, 10, 6, config())
    assert result.current_pe.tolist() == [20.0, 10.0, 12.0]
    assert result.temperature.tolist() == [0.5, 0.0, 0.0]
    assert reference.loc[reference.date.eq(pd.Timestamp("2010-06-30")), "pe"].isna().all()
    assert reference.loc[reference.date.eq(pd.Timestamp("2010-07-31")), "pe"].iloc[0] == 20
    changed = source.copy()
    changed.loc[
        changed.date > dates[-1], ["monthly_average_price", "interpolated_earnings_12m"]
    ] = 1e6
    pd.testing.assert_frame_equal(
        result, current_pe_temperature(prices, changed, 10, 6, config())[0], check_exact=True
    )
    pd.testing.assert_frame_equal(
        result,
        current_pe_temperature(prices, source[source.date <= dates[-1]], 10, 6, config())[0],
        check_exact=True,
    )


def test_missing_newly_available_earnings_and_stale_earnings_are_not_cheap():
    source = monthly()
    source.loc[source.date.eq(pd.Timestamp("2022-06-30")), "interpolated_earnings_12m"] = 0
    prices = pd.Series(100.0, index=pd.to_datetime(["2023-01-03", "2023-01-04"]))
    result, _ = current_pe_temperature(prices, source, 10, 6, config())
    assert result.current_pe.isna().all() and result.temperature.isna().all()
    prices = pd.Series(100.0, index=pd.to_datetime(["2023-02-20", "2023-02-21"]))
    result, _ = current_pe_temperature(prices, monthly().iloc[:150], 10, 6, config())
    assert result.temperature.isna().all()


def test_registry_retains_both_exits_all_core_and_neighbor_cases():
    primary = load_config(ROOT / "configs/cash_pool.yaml")
    cases = current_pe_registry(config(), primary)
    assert len(cases) == 60
    assert len({case["id"] for case in cases}) == 60
    assert {case["policy"]["exit"] for case in cases} == {"valuation_time", "valuation_tiers"}
    assert {case["policy"]["core_fraction"] for case in cases} == {0, 0.5}
    assert {case["observation_lag_months"] for case in cases} == {6, 12}


def test_saved_current_pe_case_uses_the_common_independently_verified_cash_engine(tmp_path):
    primary = load_config(ROOT / "configs/cash_pool.yaml")
    spec = config()
    cases = current_pe_registry(spec, primary)
    cases = [
        case
        for case in cases
        if case["policy"]["entry"] == "valuation"
        and case["policy"]["exit"] == "valuation_time"
        and case["policy"]["core_fraction"] == 0
        and case["window"] == 10
        and case["observation_lag_months"] == 6
        and case["scope"] == "all"
    ]
    assert len(cases) == 1
    manifest = DataCatalog(tmp_path).ingest(
        "shiller_monthly",
        b"synthetic fixture only",
        monthly(),
        source={"publisher": "test"},
        parser_version="test",
        quality={"pit_verified": False},
    )
    root = tmp_path / "study"
    (root / "inputs").mkdir(parents=True)
    dates = pd.bdate_range("2021-01-04", periods=650)
    bars = pd.DataFrame({"close": np.linspace(100, 65, len(dates))}, index=dates)
    bars.to_parquet(root / "inputs/sp500.parquet")
    write_json(
        root / "registration.json",
        {
            "config": primary,
            "current_pe_config": spec,
            "catalog_versions": {"shiller_monthly": manifest["version"]},
            "experiments": cases,
        },
    )
    outcome = _run_asset(
        {
            "directory": str(root),
            "data_root": str(tmp_path),
            "asset": {"id": "sp500", "index": "SP500", "name": "fixture", "market": "US"},
            "evidence": {"basis": "test_fixture"},
            "research_start": str(dates[252].date()),
        }
    )
    assert set(outcome["statuses"]) == {"computed"}
    results = pd.read_parquet(root / "sp500/results.parquet")
    assert results.independent_ledger_verified.all()
    assert results.formal_accepted.eq(False).all()
    assert list((root / "sp500/valuation_inputs").glob("daily_*.parquet"))
    record = json.loads(next((root / "sp500").glob("currentpe*/*/record.json")).read_text())
    assert record["valuation_source"] == "shiller_current_price_proxy"
    assert record["ending_wealth"] != pytest.approx(record["contributed"])
