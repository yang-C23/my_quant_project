import numpy as np
import pandas as pd

from quant.longterm.release_audit import quarantine_factor


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
