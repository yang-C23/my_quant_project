#!/usr/bin/env python3
"""Verify appended source observations cannot rewrite earlier pressure features.

Use PYTHONPATH from the frozen extension worktree. The expiry calendar remains
the registered calendar in both comparisons; this is a causality check, not
proof that historical exchange holiday notices or release timestamps were known.
"""

from pathlib import Path
import argparse
import json

import pandas as pd

from quant.data.catalog import DataCatalog
from quant.data.snapshots import sha256_file, write_json
from quant.etl.restart import code_revision
from quant.longterm.derivative_features import factor_confirmation
from quant.longterm.pool_extensions import load_study_asset
from quant.longterm.pressure_research import lag_observations, pressure_inputs
from quant.longterm.stages import StageSpec, stage_features


class TruncatedCatalog:
    """Read exactly the registered vintage, withholding later observations."""

    def __init__(self, catalog: DataCatalog, cutoff: pd.Timestamp):
        self.catalog, self.cutoff = catalog, cutoff

    def read(self, dataset: str, *, version: str) -> pd.DataFrame:
        frame = self.catalog.read(dataset, version=version)
        return frame[pd.to_datetime(frame.date) <= self.cutoff].copy()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extensions", type=Path)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cutoff", default="2023-12-29")
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise ValueError("preserve previous verification")
    registration_path = arguments.extensions / "registration.json"
    registration = json.loads(registration_path.read_text())
    source = Path(registration["source"])
    primary = json.loads((source / "registration.json").read_text())["config"]
    config = registration["config"]
    versions = registration["catalog_versions"]
    catalog = DataCatalog(arguments.data_root)
    cutoff = pd.Timestamp(arguments.cutoff)
    full = pressure_inputs(source, catalog, versions, config)
    truncated = pressure_inputs(source, TruncatedCatalog(catalog, cutoff), versions, config)
    rows = []
    for original, shortened in zip(full, truncated, strict=True):
        asset, factor, raw, _ = original
        other_asset, other_factor, past_raw, _ = shortened
        assert (asset, factor) == (other_asset, other_factor)
        if "evidence" not in raw:
            raise AssertionError(f"cannot verify missing source: {asset}/{factor}")
        pd.testing.assert_frame_equal(raw.loc[:cutoff], past_raw.loc[:cutoff], check_exact=True)
        bars, signals, _ = load_study_asset(source, asset)
        prefix_bars, prefix_signals = bars.loc[:cutoff], signals.loc[:cutoff]
        full_stages = stage_features(signals, StageSpec(**primary["stages"]))
        past_stages = stage_features(prefix_signals, StageSpec(**primary["stages"]))
        for lag in config["derivatives"]["publication_lag_sessions"]:
            ttl = config["additional_pressure"]["ttl_calendar_days"]
            aligned = lag_observations(raw, bars.index, lag, ttl)
            past_aligned = lag_observations(past_raw.loc[:cutoff], prefix_bars.index, lag, ttl)
            pd.testing.assert_frame_equal(aligned.loc[:cutoff], past_aligned, check_exact=True)
            confirmations = []
            for stages, observations in (
                (full_stages, aligned),
                (past_stages, past_aligned),
            ):
                confirmations.append(
                    factor_confirmation(
                        stages,
                        observations.extreme.eq(1),
                        observations.relieved.eq(1),
                        observations.evidence.notna(),
                        confirmation=primary["stages"]["confirmation"],
                    )
                )
            pd.testing.assert_series_equal(
                confirmations[0].loc[:cutoff], confirmations[1], check_exact=True
            )
            rows.append(
                {
                    "asset": asset,
                    "factor": factor,
                    "lag_sessions": lag,
                    "known_past_dates": int(past_aligned.evidence.notna().sum()),
                    "past_confirmations": int(confirmations[1].sum()),
                    "passed": True,
                }
            )
        print(asset, factor, "passed", flush=True)
    write_json(
        arguments.output,
        {
            "source_registration_sha256": sha256_file(registration_path),
            "verification_script_sha256": sha256_file(Path(__file__)),
            "research_code": code_revision(),
            "cutoff": arguments.cutoff,
            "expiry_calendar": "same_registered_calendar_not_historical_notice_proof",
            "release_timestamps": "assumed_lags_not_historical_release_proof",
            "comparisons": rows,
            "all_passed": bool(rows) and all(row["passed"] for row in rows),
        },
    )


if __name__ == "__main__":
    main()
