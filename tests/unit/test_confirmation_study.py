from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from quant.config import load_config
from quant.longterm.confirmation_study import confirmation_registry
from quant.longterm.pool_registry import pool_registry
from quant.longterm.stages import StageSpec, stage_features


def test_late_recovery_requires_longer_event_memory_and_is_causal():
    # Persistent selling lasts beyond the original twenty-session expiry.
    prices = np.r_[
        100 + np.sin(np.arange(260)),
        np.linspace(75, 50, 36),
        np.linspace(51, 80, 30),
    ]
    bars = pd.DataFrame({"close": prices}, index=pd.bdate_range("2020-01-01", periods=len(prices)))
    short = stage_features(bars)
    spec = replace(StageSpec(), event_window=60)
    longer = stage_features(bars, spec)
    assert short.pressure.equals(longer.pressure)
    assert not short.stabilized.any()
    assert longer.stabilized.any()
    assert longer.loc[longer.stabilized, "event_age"].min() > 20
    pd.testing.assert_frame_equal(
        longer.iloc[:-10], stage_features(bars.iloc[:-10], spec), check_exact=True
    )


def test_all_confirmation_variants_preserve_registered_funding_and_costs():
    root = Path(__file__).resolve().parents[2]
    primary = load_config(root / "configs/cash_pool.yaml")
    config = load_config(root / "configs/confirmation_horizon.yaml")
    old = pool_registry(primary)
    result = confirmation_registry({"experiments": old}, config)
    assert len(result) == 15
    lookup = {row["id"]: row for row in old}
    for row in result:
        if row["id"].startswith("confirmation_"):
            policy = row["policy"]
            original = lookup[f"pool_{policy['entry']}_core{policy['core_fraction']:g}"]
            assert policy == original["policy"]
            assert {k: v for k, v in row["stages"].items() if k != "event_window"} == {
                k: v for k, v in original["stages"].items() if k != "event_window"
            }
