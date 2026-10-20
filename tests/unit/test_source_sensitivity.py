"""Alternative quotations must retain the same investment and funding calendar."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant.config import load_config
from quant.data.snapshots import write_json
from quant.longterm.pool_registry import pool_registry
from quant.longterm.source_sensitivity import _source_asset


def test_vendor_sensitivity_retains_losing_case_and_rejects_a_missing_date(tmp_path):
    config = load_config(Path(__file__).resolve().parents[2] / "configs/cash_pool.yaml")
    ids = ["pool_unconditional_core0", "pool_stabilized_core0"]
    primary = {
        "config": config,
        "experiments": [
            experiment for experiment in pool_registry(config) if experiment["id"] in ids
        ],
    }
    (tmp_path / "inputs").mkdir()
    write_json(tmp_path / "registration.json", {"primary": primary, "config": {"experiments": ids}})
    dates = pd.bdate_range("2010-01-04", periods=800)
    prices = np.r_[np.full(260, 10.0), np.linspace(10, 5, 540)]
    original = pd.DataFrame(
        {
            "open": prices,
            "high": prices + 0.1,
            "low": prices - 0.1,
            "close": prices,
            "volume": 1000,
        },
        index=dates,
    )
    original.to_parquet(tmp_path / "inputs/X_tdx.parquet")
    alternative = original.copy()
    alternative.loc[dates[500] :, ["open", "high", "low", "close"]] *= 0.95
    alternative.to_parquet(tmp_path / "inputs/X_baostock.parquet")
    rows = _source_asset(("X", str(tmp_path)))
    assert len(rows) == 4
    assert {row["vendor"] for row in rows} == {"tdx", "baostock"}
    assert all(row["independent_ledger_verified"] for row in rows)
    losses = [row for row in rows if row["experiment"] == "pool_unconditional_core0"]
    assert all(row["ending_wealth"] < row["contributed"] for row in losses)
    assert losses[0]["ending_wealth"] != losses[1]["ending_wealth"]
    assert len({(row["start"], row["end"], row["contributed"]) for row in rows}) == 1
    alternative.drop(dates[500]).to_parquet(tmp_path / "inputs/X_baostock.parquet")
    with pytest.raises(ValueError, match="funding or observation calendar"):
        _source_asset(("X", str(tmp_path)))
