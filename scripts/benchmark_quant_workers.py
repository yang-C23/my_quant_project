#!/usr/bin/env python3
"""Replay a prespecified account workload with bounded process-level concurrency."""

import argparse
from concurrent.futures import ProcessPoolExecutor
import fcntl
from functools import lru_cache
import json
import multiprocessing as mp
import os
from pathlib import Path
import resource
import threading
import time

import pandas as pd
import psutil
import pyarrow as pa
from threadpoolctl import threadpool_info, threadpool_limits

from quant.config import load_config
from quant.data.snapshots import sha256_file, write_json
from quant.etl.restart import code_revision
from quant.longterm.action_audit import verify_action_ledger
from quant.longterm.cash_pool import PoolPolicy, run_cash_pool
from quant.longterm.diagnostics import verify_price_ledger
from quant.longterm.ledger import Costs, dec
from quant.longterm.pool_extensions import load_study_asset
from quant.longterm.research import save_result
from quant.longterm.stages import StageSpec, stage_features

_THREAD_LIMIT = None


def initialize_worker():
    global _THREAD_LIMIT
    _THREAD_LIMIT = threadpool_limits(limits=1)
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)


@lru_cache(maxsize=8)
def prepare(source: str, asset: str):
    root = Path(source)
    registered = json.loads((root / "registration.json").read_text())
    bars, signals, actions = load_study_asset(root, asset)
    supplemental = pd.read_parquet(root / asset / "supplemental.parquet")
    features = stage_features(
        signals, StageSpec(**registered["config"]["stages"]), supplemental=supplemental
    )
    # Feature identity is checked on every loaded asset, including NaNs and ties.
    pd.testing.assert_frame_equal(
        features, pd.read_parquet(root / asset / "stages.parquet"), check_exact=True
    )
    config = registered["config"]["execution"]
    costs = Costs(
        **{
            key: dec(config[key])
            for key in ("commission_rate", "minimum_commission", "slippage_bps")
        }
    )
    coverage = {x["asset"]: x for x in json.loads((root / "coverage.json").read_text())}
    assets = {x["id"]: x for x in registered["universe"]}
    symbol = coverage[asset].get("symbol", assets[asset]["index"])
    return bars, actions, features, costs, symbol


def run_case(job: dict) -> dict:
    started, cpu = time.perf_counter(), time.process_time()
    source, case_id, output = Path(job["source"]), job["case"], Path(job["output"])
    record = json.loads((source / case_id / "record.json").read_text())
    phases = {}
    tick = time.perf_counter()
    bars, actions, features, costs, symbol = prepare(str(source), record["asset"])
    phases["read_prepare_cached"] = time.perf_counter() - tick
    tick = time.perf_counter()
    result = run_cash_pool(
        bars,
        features,
        PoolPolicy(**json.loads(record["policy_json"])),
        symbol=symbol,
        start=record["start"],
        end=record["end"],
        costs=costs,
        lot=dec(100 if actions is not None else 0.000001),
        actions=actions,
        price_basis="raw",
        execution="next_close",
    )
    phases["account"] = time.perf_counter() - tick
    tick = time.perf_counter()
    audit = (
        verify_price_ledger(result, bars.close)
        if actions is None
        else verify_action_ledger(result, bars.close, actions, costs)
    )
    phases["independent_audit"] = time.perf_counter() - tick
    tick = time.perf_counter()
    case = output / case_id
    save_result(result, case)
    write_json(case / "ledger_audit.json", audit)
    phases["write"] = time.perf_counter() - tick
    comparisons = {
        path.name: sha256_file(path) == sha256_file(source / case_id / path.name)
        for path in case.iterdir()
    }
    if not all(comparisons.values()):
        raise AssertionError(f"financial payload changed: {case_id} {comparisons}")
    return {
        "case": case_id,
        "pid": os.getpid(),
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu,
        "peak_worker_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "phases": phases,
        "exact_files": comparisons,
        "threadpools": threadpool_info(),
    }


def run_asset_batch(jobs):
    return [run_case(job) for job in jobs]


def sample_resources(stop, samples):
    process = psutil.Process()
    while not stop.is_set():
        row = {"at": time.perf_counter(), "cpu_seconds": 0, "rss": 0, "uss": 0, "threads": 0}
        for item in [process, *process.children(recursive=True)]:
            try:
                cpu = item.cpu_times()
                memory = item.memory_full_info()
                row["cpu_seconds"] += cpu.user + cpu.system
                row["rss"] += memory.rss
                row["uss"] += memory.uss
                row["threads"] += item.num_threads()
            except psutil.Error:
                pass
        row["available_memory"] = psutil.virtual_memory().available
        row["system_cpu_percent"] = psutil.cpu_percent()
        samples.append(row)
        stop.wait(0.1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--scheduling", choices=["case", "asset"], default="case")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    if not 1 <= args.workers <= len(os.sched_getaffinity(0)) - config["reserve_logical_cpus"]:
        raise ValueError("worker count exceeds the reserved CPU budget")
    if args.output.exists():
        raise ValueError("preserve earlier benchmark evidence")
    # Only one benchmark controller may expand workers at a time.
    lock = Path("/tmp/quant-throughput-benchmark.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    args.output.mkdir(parents=True)
    jobs = [
        {"source": str(args.source), "output": str(args.output), "case": f"{a}/{e}/{w}"}
        for a in config["assets"]
        for e in config["experiments"]
        for w in config["windows"]
        if (args.source / a / e / w / "record.json").exists()
    ]
    write_json(
        args.output / "registration.json",
        {
            "code": code_revision(),
            "benchmark_script_sha256": sha256_file(Path(__file__).resolve()),
            "source": str(args.source),
            "config": config,
            "workers": args.workers,
            "scheduling": args.scheduling,
            "cases": [j["case"] for j in jobs],
            "inputs": {
                str(path.relative_to(args.source)): sha256_file(path)
                for path in (args.source / "inputs").glob("*.parquet")
                if path.stem.removesuffix("_actions") in config["assets"]
            },
        },
    )
    samples, stop = [], threading.Event()
    monitor = threading.Thread(target=sample_resources, args=(stop, samples), daemon=True)
    before_self, before_children = resource.getrusage(0), resource.getrusage(-1)
    disk_before = psutil.disk_io_counters()
    start = time.perf_counter()
    monitor.start()
    try:
        with ProcessPoolExecutor(
            max_workers=args.workers,
            mp_context=mp.get_context("spawn"),
            initializer=initialize_worker,
        ) as pool:
            if args.scheduling == "case":
                results = list(pool.map(run_case, jobs, chunksize=1))
            else:
                batches = [
                    [job for job in jobs if job["case"].startswith(asset + "/")]
                    for asset in config["assets"]
                ]
                results = [row for batch in pool.map(run_asset_batch, batches) for row in batch]
    finally:
        elapsed = time.perf_counter() - start
        stop.set()
        monitor.join()
    after_self, after_children = resource.getrusage(0), resource.getrusage(-1)
    cpu = sum(
        after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime
        for before, after in ((before_self, after_self), (before_children, after_children))
    )
    disk_after = psutil.disk_io_counters()
    summary = {
        "accounts": len(results),
        "wall_seconds": elapsed,
        "cpu_seconds_including_process_start": cpu,
        "average_cpu_cores": cpu / elapsed,
        "accounts_per_second": len(results) / elapsed,
        "peak_sum_rss_bytes_including_shared": max(s["rss"] for s in samples),
        "peak_sum_uss_bytes": max(s["uss"] for s in samples),
        "peak_threads": max(s["threads"] for s in samples),
        "min_system_available_memory": min(s["available_memory"] for s in samples),
        "system_disk_read_bytes_including_other_jobs": disk_after.read_bytes
        - disk_before.read_bytes,
        "system_disk_write_bytes_including_other_jobs": disk_after.write_bytes
        - disk_before.write_bytes,
        "workers": args.workers,
        "scheduling": args.scheduling,
        "all_payloads_exact": all(all(x["exact_files"].values()) for x in results),
        "sample_interval_seconds": 0.1,
    }
    write_json(args.output / "cases.json", sorted(results, key=lambda r: r["case"]))
    write_json(args.output / "summary.json", summary)
    pd.DataFrame(samples).to_csv(args.output / "resources.csv", index=False)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
