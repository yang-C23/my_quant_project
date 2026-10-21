#!/usr/bin/env python3
"""Summarize every completed CPU repetition and both actual GPU experiments."""

import argparse
import json
from pathlib import Path

import matplotlib
import pandas as pd

from quant.config import load_config
from quant.data.snapshots import sha256_file, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--selection", type=Path, default=Path("configs/performance_selection.yaml")
    )
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("preserve earlier performance summaries")
    selection = load_config(args.selection)
    rows, hashes, reference_cases = [], {}, None
    for path in sorted(args.source.glob("cpu-*/summary.json")):
        row = json.loads(path.read_text())
        registration = json.loads(path.with_name("registration.json").read_text())
        if row["accounts"] != 52 or not row["all_payloads_exact"]:
            raise AssertionError("all workload accounts must pass exact validation")
        cases = registration["cases"]
        if reference_cases is not None and cases != reference_cases:
            raise AssertionError("benchmark workloads differ")
        reference_cases = cases
        row["implementation"] = "original" if "baseline" in path.parent.name else "optimized"
        row["run"] = path.parent.name
        rows.append(row)
        hashes[str(path.relative_to(args.source))] = sha256_file(path)
    table = pd.DataFrame(rows)
    grouped = (
        table.groupby(["implementation", "workers"], sort=True)
        .agg(
            repetitions=("wall_seconds", "size"),
            median_seconds=("wall_seconds", "median"),
            minimum_seconds=("wall_seconds", "min"),
            maximum_seconds=("wall_seconds", "max"),
            average_cpu_cores=("average_cpu_cores", "median"),
            peak_rss_bytes=("peak_sum_rss_bytes_including_shared", "max"),
            peak_uss_bytes=("peak_sum_uss_bytes", "max"),
        )
        .reset_index()
    )
    optimized = grouped[grouped.implementation.eq("optimized")]
    if set(optimized.workers) != {1, 2, 4, 6, 8, 12, 16} or not optimized.repetitions.eq(3).all():
        raise AssertionError("complete declared ladder and all repetitions before selection")
    best = optimized.median_seconds.min()
    chosen = optimized[optimized.median_seconds <= best * 1.05].workers.min()
    chosen_row = optimized[optimized.workers.eq(chosen)].iloc[0]
    baseline = grouped[grouped.implementation.eq("original") & grouped.workers.eq(4)].iloc[0]
    args.output.mkdir(parents=True)
    table.to_csv(args.output / "all_cpu_trials.csv", index=False)
    grouped["accounts_per_second"] = 52 / grouped.median_seconds
    grouped.to_csv(args.output / "cpu_summary.csv", index=False)
    gpu = pd.concat(
        [
            pd.read_csv(args.source / run / "timings.csv").assign(run=run)
            for run in ("gpu-v3", "gpu-v4")
        ]
    )
    gpu.to_csv(args.output / "all_gpu_trials.csv", index=False)
    summary = {
        "selected_workers": int(chosen),
        "rule": selection["rule"],
        "median_selected_seconds": float(chosen_row.median_seconds),
        "original_four_workers_median_seconds": float(baseline.median_seconds),
        "speedup_vs_original_four_workers": float(
            baseline.median_seconds / chosen_row.median_seconds
        ),
        "all_cpu_runs": len(table),
        "all_cpu_account_replays": int(table.accounts.sum()),
        "all_payloads_exact": True,
        "scope": "fixed_52_accounts_including_worker_start_IO_audit_write_hash",
        "main_interpreter_import_and_registration_precede_workload_timer": True,
    }
    write_json(args.output / "summary.json", summary)
    write_json(
        args.output / "registration.json",
        {
            "source": str(args.source),
            "input_summary_hashes": hashes,
            "selection": selection,
            "script_sha256": sha256_file(Path(__file__)),
            "selection_file_sha256": sha256_file(args.selection),
        },
    )
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["svg.hashsalt"] = "quant-performance-20261020"
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), layout="constrained")
    for label, group in grouped.groupby("implementation"):
        axes[0].plot(group.workers, group.accounts_per_second, marker="o", label=label)
    axes[0].set(
        xlabel="Worker processes",
        ylabel="Accounts / second",
        title="Same 52 accounts; complete workload timing",
    )
    axes[0].legend()
    axes[0].grid(alpha=0.25)
    labels = ["CPU original", "CPU optimized", "GPU cold", "GPU warm"]
    keys = [
        "cpu_original",
        "cpu_optimized",
        "gpu_cold_import_context_compile_transfer_compute_download",
        "gpu_warm_full_call",
    ]
    latency = gpu.groupby("label").wall_seconds.median()
    axes[1].bar(labels, [latency[key] * 1000 for key in keys])
    axes[1].set(
        yscale="log",
        ylabel="Milliseconds (log scale)",
        title="22,851 actual observations; transfers included",
    )
    axes[1].tick_params(axis="x", rotation=15)
    for ext in ("png", "svg"):
        fig.savefig(
            args.output / f"throughput.{ext}",
            dpi=160,
            metadata={"Date": None} if ext == "svg" else {},
        )
    plt.close(fig)
    write_json(
        args.output / "payloads.json",
        {
            path.name: sha256_file(path)
            for path in sorted(args.output.iterdir())
            if path.name != "registration.json"
        },
    )
    print(grouped.to_string(index=False))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
