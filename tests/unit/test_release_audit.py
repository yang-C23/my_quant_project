import numpy as np
import pandas as pd

from quant.longterm.release_audit import quarantine_factor
from quant.longterm.pool_data import apply_publication_bounds
from quant.longterm.features import align_available


def test_release_bounds_preserve_known_observation_and_expire_it():
    dates = pd.to_datetime(["2018-12-18", "2018-12-24", "2019-03-26", "2019-04-02"])
    source = pd.DataFrame(
        {
            "date": dates,
            "available_at": (dates + pd.Timedelta(days=10, hours=23, minutes=59)).tz_localize(
                "UTC"
            ),
            "value": [0.1, 0.9, 0.7, 0.6],
        }
    )
    bounds = [{"start": "2018-12-22", "end": "2019-03-31"}]
    adjusted = apply_publication_bounds(source, bounds)
    decisions = pd.to_datetime(
        ["2019-01-02 21:00", "2019-01-07 21:00", "2019-01-14 21:00", "2019-04-08 20:00"],
        utc=True,
    )
    values = align_available(adjusted, decisions, "value", maximum_age_days=24)
    assert values.iloc[:2].tolist() == [0.1, 0.1]
    assert pd.isna(values.iloc[2])
    assert values.iloc[3] == 0.7
    assert adjusted.available_at.iloc[0] == source.available_at.iloc[0]
    assert adjusted.available_at.iloc[3] == source.available_at.iloc[3]
    pd.testing.assert_frame_equal(
        adjusted.iloc[:2], apply_publication_bounds(source.iloc[:2], bounds)
    )
    pd.testing.assert_series_equal(
        values.iloc[:3],
        align_available(adjusted.iloc[:2], decisions[:3], "value", maximum_age_days=24),
    )


def test_quarantine_preserves_other_factors_and_does_not_change_original():
    dates = pd.bdate_range("2025-09-29", periods=5)
    frame = pd.DataFrame({"positions": 0.2, "vix": 30.0}, index=dates)
    config = {
        "factor": "positions",
        "quarantine": [{"start": "2025-09-30", "end": "2025-10-01"}],
    }
    output, mask = quarantine_factor(frame, config)
    assert list(mask) == [False, True, True, False, False]
    assert output.loc[mask, "positions"].isna().all()
    assert output.loc[~mask, "positions"].eq(0.2).all()
    assert output.vix.eq(30).all() and np.isfinite(frame).all().all()
    prefix, _ = quarantine_factor(frame.iloc[:3], config)
    pd.testing.assert_frame_equal(prefix, output.iloc[:3])
