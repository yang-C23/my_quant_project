"""Confirm-event expiry sensitivity using the shared, audited account engine."""

from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import shutil

import pandas as pd

from quant.config import Settings, load_config
from quant.data.snapshots import sha256_file, utc_now, write_json
from quant.etl.restart import code_revision
from quant.longterm.pool_analysis import window_summary
from quant.longterm.pool_extensions import load_study_asset
from quant.longterm.pool_research import _run_asset, make_pool_report
from quant.longterm.stages import StageSpec, event_study, stage_features


def confirmation_registry(primary: dict, config: dict) -> list[dict]:
    """Freeze all expiry/entry/core combinations without selecting their outcomes."""
    originals = {row["id"]: row for row in primary["experiments"]}
    rows = [deepcopy(originals[name]) for name in config["controls"]]
    for window in config["confirmation_windows_sessions"]:
        for entry in config["entries"]:
            for core in config["core_fractions"]:
                row = deepcopy(originals[f"pool_{entry}_core{core:g}"])
                row["id"] = f"confirmation_{window}_{entry}_core{core:g}"
                row["stages"]["event_window"] = window
                StageSpec(**row["stages"])
                row["scope"] = "primary"
                rows.append(row)
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("duplicate confirmation experiment")
    return rows


def run_confirmation_study(
    settings: Settings,
    source: Path,
    destination: Path,
    config_path: Path,
    *,
    workers: int = 4,
    replay_run: Path | None = None,
) -> dict:
    """Change stage expiry only, preserving raw bars/actions and all original accounts."""
    if destination.exists() or workers < 1:
        raise ValueError("new destination and positive workers required")
    config = load_config(config_path)
    prior = json.loads((source / "registration.json").read_text())
    primary = deepcopy(prior["config"])
    primary["validation"]["rolling_years"] = config["rolling_years"]
    registration = prior | {
        "registered_at": utc_now(),
        "parent_primary_run": str(source),
        "parent_registration_sha256": sha256_file(source / "registration.json"),
        "config": primary,
        "confirmation_config": config,
        "config_sha256": sha256_file(config_path),
        "code": code_revision(),
        "experiments": confirmation_registry(prior, config),
        "input_hashes": {
            path.name: sha256_file(path) for path in sorted((source / "inputs").glob("*.parquet"))
        },
        "formal_accepted": False,
        "selection": "all_expiry_variants_after_observing_the_original_results",
    }
    if replay_run:
        original = json.loads((replay_run / "registration.json").read_text())
        for key in ("parent_registration_sha256", "config", "confirmation_config", "input_hashes"):
            if original[key] != registration[key]:
                raise ValueError(f"confirmation replay input mismatch: {key}")
        if original["code"]["sources"] != registration["code"]["sources"]:
            raise ValueError("confirmation replay requires identical source bytes")
        registration = original
    destination.mkdir(parents=True)
    shutil.copytree(source / "inputs", destination / "inputs")
    write_json(destination / "registration.json", registration)
    coverage = json.loads((source / "coverage.json").read_text())
    write_json(destination / "coverage.json", coverage)
    assets = {row["id"]: row for row in registration["universe"]}
    jobs, unavailable = [], []
    for evidence in coverage:
        name = evidence["asset"]
        if evidence.get("status") == "blocked":
            unavailable.extend(
                {
                    "asset": name,
                    "experiment": experiment["id"],
                    "status": "blocked",
                    "reason": evidence["reason"],
                }
                for experiment in registration["experiments"]
            )
            continue
        jobs.append(
            {
                "directory": str(destination),
                "data_root": str(settings.data_root),
                "asset": assets[name],
                "evidence": evidence,
                "actions": evidence.get("corporate_actions_dataset"),
                "research_start": evidence["funding_start_after_shared_warmup"],
            }
        )
    with ProcessPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(_run_asset, jobs))
    events = []
    for job in jobs:
        name = job["asset"]["id"]
        _, signals, _ = load_study_asset(destination, name)
        for window in config["confirmation_windows_sessions"]:
            spec = StageSpec(**(primary["stages"] | {"event_window": window}))
            stages = stage_features(signals, spec)
            stages.to_parquet(
                destination / name / f"confirmation_{window}_stages.parquet", compression="zstd"
            )
            events.append(
                event_study(
                    signals,
                    stages,
                    forward_sessions=tuple(primary["validation"]["event_horizons_sessions"]),
                ).assign(asset=name, confirmation_window=window)
            )
    pd.concat(events, ignore_index=True).to_parquet(
        destination / "confirmation_events.parquet", compression="zstd"
    )
    table = pd.concat(
        [
            *(
                pd.read_parquet(destination / job["asset"]["id"] / "results.parquet")
                for job in jobs
            ),
            pd.DataFrame(unavailable),
        ],
        ignore_index=True,
    )
    table.to_parquet(destination / "results.parquet", compression="zstd")
    table.to_csv(destination / "results.csv", index=False)
    window_summary(table).to_csv(destination / "windows_all.csv", index=False)
    summary = {
        "experiments": len(registration["experiments"]),
        "records": len(table),
        "statuses": table.status.value_counts().to_dict(),
        "outcomes": outcomes,
        "formal_accepted": False,
    }
    make_pool_report(destination, table, coverage, summary)
    write_json(destination / "summary.json", summary)
    payloads = {
        str(path.relative_to(destination)): sha256_file(path)
        for path in sorted(destination.rglob("*"))
        if path.is_file()
        and path.name not in {"registration.json", "summary.json", "progress.json"}
    }
    write_json(destination / "payloads.json", payloads)
    if replay_run:
        old = json.loads((replay_run / "payloads.json").read_text())
        changed = sorted(k for k in set(old) | set(payloads) if old.get(k) != payloads.get(k))
        write_json(
            destination / "replay.json",
            {"identical": not changed, "changed_files": changed, "payloads": len(payloads)},
        )
    return summary
