import numpy as np
import pandas as pd

from quant.longterm.stages import StageSpec, event_study, qualify_value_events, stage_features


def test_low_valuation_must_precede_confirmation_not_be_assigned_backwards():
    rows = pd.DataFrame(
        {
            "temperature": [0.6, 0.3, 0.2, 0.3, 0.6, 0.3],
            "event_id": [1, 1, 1, 2, 2, 2],
            "pressure": [True, False, False, True, False, False],
        },
        index=pd.bdate_range("2020-01-01", periods=6),
    )
    qualified = qualify_value_events(rows, 0.4)
    assert qualified.event_value_eligible.tolist() == [False, False, False, True, True, True]
    pd.testing.assert_frame_equal(qualify_value_events(rows.iloc[:4], 0.4), qualified.iloc[:4])


def stress_prices():
    base = 100 + np.sin(np.arange(270) * 0.7)
    path = np.r_[base, [98, 94, 88, 80, 74, 70, 72, 73, 74, 75, 76, 77, 78, 79, 80], [80] * 50]
    return pd.DataFrame({"close": path}, index=pd.bdate_range("2000-01-03", periods=len(path)))


def test_stages_are_causal_and_have_distinct_confirmations():
    bars = stress_prices()
    stages = stage_features(bars)
    shorter = stage_features(bars.iloc[:290])
    pd.testing.assert_frame_equal(stages.iloc[:290], shorter)
    assert stages["pressure"].sum() == 1
    assert stages["stabilized"].sum() == 1
    assert stages["relief"].sum() == 1
    assert stages.index[stages.stabilized][0] > stages.index[stages.pressure][0]
    assert stages.loc[stages.stabilized, "sessions_since_event_low"].iloc[0] >= 5
    assert not stages.vix_relief.any()


def test_pre_shock_volatility_excludes_all_five_shock_returns():
    bars = stress_prices()
    stages = stage_features(bars, StageSpec(volatility_lag=5))
    i = 274
    expected = bars.close.pct_change().iloc[i - 64 : i - 4].std(ddof=1)
    assert abs(stages.iloc[i].pre_shock_volatility - expected) < 1e-12


def test_event_study_keeps_missing_confirmation_and_censored_outcomes():
    bars = stress_prices()
    stages = stage_features(bars)
    events = event_study(bars, stages)
    assert len(events) == 6
    absent = events[events.stage.eq("vix_relief")].iloc[0]
    assert absent.status == "factor_unavailable"
    assert pd.isna(absent.event_horizon_return_20)
    assert events.forward_return_1260.isna().all()
    immediate = events[events.stage.eq("pressure")].iloc[0]
    signal = bars.index.get_loc(pd.Timestamp(immediate.signal_date))
    assert immediate.entry_date == str(bars.index[signal + 1].date())
    supplied = pd.DataFrame({"vix": 15.0, "vix_percentile": 0.5}, index=bars.index)
    no_entry = event_study(bars, stage_features(bars, supplemental=supplied))
    observed = no_entry[no_entry.stage.eq("vix_relief")].iloc[0]
    assert observed.status == "no_confirmation_in_window"
    assert observed.event_horizon_return_20 == 0


def test_vix_peak_and_relief_use_only_available_history():
    bars = stress_prices()
    supplemental = pd.DataFrame({"vix": 15.0, "vix_percentile": 0.5}, index=bars.index)
    supplemental.iloc[270:277] = [50.0, 0.95]
    supplemental.iloc[277:] = [25.0, 0.75]
    features = stage_features(bars, supplemental=supplemental)
    assert features.vix_relief.sum() == 1
    cutoff = 280
    pd.testing.assert_frame_equal(
        features.iloc[:cutoff],
        stage_features(bars.iloc[:cutoff], supplemental=supplemental.iloc[:cutoff]),
    )
