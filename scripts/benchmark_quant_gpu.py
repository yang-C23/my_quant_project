#!/usr/bin/env python3
"""CPU/GPU comparison on actual Cboe series, with complete synchronous timings."""

import argparse
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import platform
import subprocess
import time

import numpy as np
import pandas as pd
import psutil

from quant.data.catalog import DataCatalog
from quant.data.snapshots import sha256_file, write_json
from quant.longterm.features import historical_percentile
from quant.longterm.gpu_features import historical_percentiles_gpu


def compare(expected, actual):
    for a, b in zip(expected, actual):
        pd.testing.assert_series_equal(a, b, check_exact=True)
        for threshold in (0.1, 0.3, 0.4, 0.7, 0.8, 0.9, 0.95):
            np.testing.assert_array_equal(a < threshold, b < threshold)
            np.testing.assert_array_equal(a >= threshold, b >= threshold)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_root", type=Path)
    parser.add_argument("baseline_source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("preserve all prior GPU experiments")
    args.output.mkdir(parents=True)
    os.environ["CUPY_CACHE_DIR"] = str(args.output / "cuda-cache")
    spec = importlib.util.spec_from_file_location(
        "frozen_features", args.baseline_source / "src/quant/longterm/features.py"
    )
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    catalog = DataCatalog(args.data_root)
    inputs, versions, observations = [], {}, []
    for name, column in (("cboe_vix", "close"), ("cboe_vxn", "close"), ("cboe_skew", "skew")):
        manifest = catalog.manifest(name)
        versions[name] = manifest["version"]
        frame = catalog.read(name, version=versions[name])
        series = pd.Series(frame[column].to_numpy(), index=pd.to_datetime(frame.date)).sort_index()
        inputs.append(series)
        observations.append(
            {
                "source": name,
                "rows": len(series),
                "start": str(series.index[0]),
                "end": str(series.index[-1]),
                "raw_sha256": manifest["raw_sha256"],
            }
        )
    write_json(
        args.output / "registration.json",
        {
            "versions": versions,
            "observations": observations,
            "real_data_not_tiled": True,
            "precision": "float64_exact_midrank_exact_signals_no_tolerance_relaxation",
            "years": 5,
            "warm_repetitions": 5,
            "baseline_features_sha256": sha256_file(Path(spec.origin)),
            "optimized_features_sha256": sha256_file(
                Path(__file__).resolve().parents[1] / "src/quant/longterm/features.py"
            ),
            "gpu_features_sha256": sha256_file(
                Path(__file__).resolve().parents[1] / "src/quant/longterm/gpu_features.py"
            ),
        },
    )
    timings = []

    def timed(label, function):
        start, cpu = time.perf_counter(), time.process_time()
        result = function()
        timings.append(
            {
                "label": label,
                "wall_seconds": time.perf_counter() - start,
                "cpu_seconds": time.process_time() - cpu,
            }
        )
        return result

    expected = timed(
        "cpu_original",
        lambda: [baseline.historical_percentile(x, years=5) for x in inputs],
    )
    for _ in range(5):
        actual = timed("cpu_optimized", lambda: [historical_percentile(x, years=5) for x in inputs])
        compare(expected, actual)
    cold = time.perf_counter()
    import cupy as cp

    gpu = historical_percentiles_gpu(inputs, years=5)
    cp.cuda.get_current_stream().synchronize()
    timings.append(
        {
            "label": "gpu_cold_import_context_compile_transfer_compute_download",
            "wall_seconds": time.perf_counter() - cold,
        }
    )
    compare(expected, gpu)
    components = []
    for _ in range(5):
        component = {}
        gpu = timed(
            "gpu_warm_full_call",
            lambda: historical_percentiles_gpu(inputs, years=5, timings=component),
        )
        components.append(component)
        compare(expected, gpu)

    # Repeated latest-day work still includes the full warmup data and transfer.
    # Also measure the efficient CPU online rank directly: GPU is not assumed
    # beneficial for three new observations.
    def latest_cpu():
        out = []
        for x in inputs:
            history = x[(x.index >= x.index[-1] - pd.DateOffset(years=5))].iloc[:-1]
            history = history.where(np.isfinite(history) & history.gt(0)).dropna()
            out.append(
                (
                    np.count_nonzero(history < x.iloc[-1])
                    + 0.5 * np.count_nonzero(history == x.iloc[-1])
                )
                / len(history)
            )
        return out

    for _ in range(5):
        latest = timed("cpu_three_latest_observations", latest_cpu)
        np.testing.assert_array_equal(latest, [x.iloc[-1] for x in expected])
    # Ties, thresholds, zero/negative/missing/inf, leap-day boundaries and
    # expanding windows. Fixtures validate semantics, never count as workload.
    dates = pd.bdate_range("2016-02-29", "2024-06-01")
    values = np.tile(np.array([1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 0.0, -1.0, np.nan, np.inf]), 300)[
        : len(dates)
    ]
    fixtures = [
        pd.Series(values, index=dates),
        pd.Series(np.ones(len(dates)), index=dates),
        pd.Series(np.nan, index=dates),
        pd.Series(values, index=dates).iloc[:0],
    ]
    fixture_count = 0
    for expanding in (False, True):
        for positive in (False, True):
            kwargs = dict(
                years=1, minimum_coverage=0.5, expanding=expanding, positive_only=positive
            )
            old = [baseline.historical_percentile(x, **kwargs) for x in fixtures]
            compare(old, [historical_percentile(x, **kwargs) for x in fixtures])
            compare(old, historical_percentiles_gpu(fixtures, **kwargs))
            fixture_count += len(fixtures)
    cut = [x.iloc[: int(len(x) * 0.75)] for x in inputs]
    prefix = historical_percentiles_gpu(cut, years=5)
    compare(prefix, [full.iloc[: len(part)] for full, part in zip(gpu, cut)])
    config = io.StringIO()
    with contextlib.redirect_stdout(config):
        cp.show_config()
    (args.output / "cupy-config.txt").write_text(config.getvalue())
    smi = subprocess.run(
        [
            "/usr/lib/wsl/lib/nvidia-smi",
            "--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu,power.draw",
            "--format=csv",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    (args.output / "gpu-after.csv").write_text(smi.stdout)
    pd.DataFrame(timings).to_csv(args.output / "timings.csv", index=False)
    pd.DataFrame(components).to_csv(args.output / "gpu_components.csv", index=False)
    write_json(
        args.output / "summary.json",
        {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "cupy": cp.__version__,
            "all_values_and_threshold_decisions_exact": True,
            "future_prefix_exact": True,
            "fixture_cases": fixture_count,
            "total_actual_observations": sum(len(x) for x in inputs),
            "host_rss_bytes_after": psutil.Process().memory_info().rss,
            "gpu_allocator_reserved_peak_bytes": cp.get_default_memory_pool().total_bytes(),
            "timing_includes": "host_preparation_H2D_synchronized_kernel_D2H_result_construction",
            "cold_includes": "CuPy_import_CUDA_context_NVRTC_compile_and_complete_first_call",
            "timings": timings,
        },
    )
    print(pd.DataFrame(timings).groupby("label").wall_seconds.agg(["min", "median", "max"]))


if __name__ == "__main__":
    main()
