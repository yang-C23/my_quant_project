"""Dependent event clusters and non-entry cash must not disappear from comparisons."""

import pandas as pd
import pytest

from quant.longterm.pool_analysis import clustered_event_comparisons, crisis_labels
from quant.longterm.pool_analysis import recovery_episodes, validate_window_horizons


def test_report_rejects_shortened_history_labelled_as_five_years():
    table = pd.DataFrame(
        [
            {
                "status": "computed",
                "asset": "X",
                "experiment": "factor",
                "window": "latest_5y",
                "start": "2017-06-02",
                "end": "2019-10-11",
            }
        ]
    )
    with pytest.raises(ValueError, match="incorrect calendar horizon"):
        validate_window_horizons(table)
    table.loc[0, "start"] = "2014-10-13"
    validate_window_horizons(table)


def test_correction_requires_original_bytes_and_preserves_original_record(tmp_path):
    from quant.data.snapshots import sha256_file, write_json
    from quant.longterm.pool_analysis import apply_calendar_corrections, daily_artifact

    source, correction = tmp_path / "source", tmp_path / "correction"
    source.mkdir()
    correction.mkdir()
    write_json(source / "registration.json", {"config": "frozen"})
    case = source / "X/rule/retrospective_train"
    case.mkdir(parents=True)
    original = {
        "asset": "X",
        "experiment": "rule",
        "window": "retrospective_train",
        "start": "2000-01-03",
        "end": "2010-11-19",
        "status": "computed",
        "result_directory": "X/rule/retrospective_train",
        "independent_ledger_verified": True,
        "ending_wealth": 200000.0,
    }
    write_json(case / "record.json", original)
    digest = sha256_file(case / "record.json")
    replacement = original | {
        "end": "2010-11-18",
        "ending_wealth": 199000.0,
        "superseded_record_sha256": digest,
    }
    pd.DataFrame([replacement]).to_parquet(correction / "results.parquet")
    write_json(
        correction / "registration.json",
        {"source_registration_sha256": sha256_file(source / "registration.json")},
    )
    write_json(
        correction / "payloads.json",
        {"results.parquet": sha256_file(correction / "results.parquet")},
    )
    updated, old = apply_calendar_corrections(source, pd.DataFrame([original]), correction)
    assert old.iloc[0].ending_wealth == 200000
    assert updated.iloc[0].ending_wealth == 199000
    assert sha256_file(case / "record.json") == digest
    assert (
        daily_artifact(source, updated.iloc[0])
        == correction / original["result_directory"] / "daily.parquet"
    )
    write_json(case / "record.json", original | {"ending_wealth": 201000})
    with pytest.raises(ValueError, match="superseded case checksum"):
        apply_calendar_corrections(source, pd.DataFrame([original]), correction)


def test_recovery_keeps_initial_cost_loss_and_open_episode_separate():
    nav = pd.Series(
        [0.99, 1.10, 0.80, 1.11, 1.01],
        index=pd.to_datetime(
            ["2020-01-01", "2020-01-02", "2020-02-02", "2020-03-02", "2020-04-02"]
        ),
    )
    episodes = recovery_episodes(nav)
    assert len(episodes) == 3
    assert episodes.iloc[0].initial_funding_peak
    assert episodes.iloc[0].elapsed_calendar_days == 1
    assert episodes.iloc[1].max_drawdown == pytest.approx(0.8 / 1.1 - 1)
    assert episodes.iloc[1].elapsed_calendar_days == 60
    assert not episodes.iloc[1].censored
    assert episodes.iloc[2].censored
    assert episodes.iloc[2].elapsed_calendar_days == 31
    assert episodes.iloc[2].recovery_date is None
    cash = pd.Series(1.0, index=nav.index)
    assert recovery_episodes(cash).empty


def test_crisis_clusters_not_daily_signal_count_and_nonentry_cash_retained():
    rows = []
    for event, date in enumerate(["2008-01-01", "2008-01-25", "2020-03-01", "2022-05-01"]):
        rows += [
            {
                "asset": "X",
                "stage": "pressure",
                "event_id": event,
                "event_date": date,
                "status": "entered",
                "event_horizon_return_252": 0.20,
            },
            {
                "asset": "X",
                "stage": "stabilized",
                "event_id": event,
                "event_date": date,
                "status": "no_confirmation_in_window",
                "event_horizon_return_252": 0.0,
            },
            {
                "asset": "X",
                "stage": "vix_relief",
                "event_id": event,
                "event_date": date,
                "status": "factor_unavailable",
                "event_horizon_return_252": None,
            },
        ]
    config = {
        "crisis_gap_days": 120,
        "bootstrap_seed": 7,
        "horizons": [252],
        "bootstrap_repetitions": 100,
    }
    results, leave_out = clustered_event_comparisons(pd.DataFrame(rows), config)
    row = results[results.stage.eq("stabilized")].iloc[0]
    assert row.paired_events == 4 and row.crisis_clusters == 3
    assert row.equal_crisis_mean_delta == pytest.approx(-0.2)
    assert row.ci_high == pytest.approx(-0.2)
    assert len(leave_out) == 3
    missing = results[results.stage.eq("vix_relief")].iloc[0]
    assert missing.paired_events == 0 and pd.isna(missing.equal_crisis_mean_delta)
    pd.testing.assert_frame_equal(
        results, clustered_event_comparisons(pd.DataFrame(rows), config)[0]
    )


def test_crisis_assignment_is_unchanged_when_later_dates_arrive():
    dates = pd.Series(["2008-01-01", "2008-01-20", "2020-03-01"])
    extended = pd.concat([dates, pd.Series(["2020-03-20", "2022-02-01"])], ignore_index=True)
    pd.testing.assert_series_equal(crisis_labels(dates, 120), crisis_labels(extended, 120).iloc[:3])


def test_extension_factor_control_matches_factor_core_and_calendar():
    from quant.longterm.pool_analysis import pair_extension_results

    base = {
        "group": "pressure",
        "asset": "csi300",
        "factor": "basis",
        "lag_sessions": 2,
        "core": 0.5,
        "window": "full",
        "status": "computed",
        "start": "2020-01-01",
        "end": "2025-01-01",
        "contributed": 160000,
        "annualized_return": 0.1,
        "max_drawdown": -0.2,
        "ending_wealth": 220000,
        "xirr": 0.11,
    }
    rows = [
        base | {"experiment": f"basis_lag2_{entry}_core0.5"}
        for entry in ("unconditional", "stabilized", "external_event")
    ]
    rows[-1]["ending_wealth"] += 1000
    output = pair_extension_results(pd.DataFrame(rows))
    assert output.iloc[-1].delta_ending_wealth_vs_pool == 1000
    assert output.iloc[-1].delta_ending_wealth_vs_extra_control == 1000
    rows[-1]["start"] = "2020-02-01"
    with pytest.raises(ValueError, match="different funding"):
        pair_extension_results(pd.DataFrame(rows))
