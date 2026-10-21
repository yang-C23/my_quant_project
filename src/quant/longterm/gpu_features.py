"""Optional, explicit GPU feature backend; never used by the cash ledger."""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

_KERNEL = r"""
extern "C" __global__ void midrank(
    const double* x, const long long* left, const unsigned char* ready,
    const long long n, const long long minimum, double* out) {
    long long i = (long long)blockDim.x * blockIdx.x + threadIdx.x;
    if (i >= n) return;
    out[i] = nan("");
    if (!ready[i]) return;
    long long valid = 0, below = 0, equal = 0;
    for (long long j = left[i]; j < i; ++j) {
        double value = x[j];
        if (!isnan(value)) {
            ++valid;
            below += value < x[i];
            equal += value == x[i];
        }
    }
    if (valid >= minimum)
        out[i] = ((double)below + (double)equal * 0.5) / (double)valid;
}
"""


def historical_percentiles_gpu(
    observations: list[pd.Series],
    *,
    years: int = 10,
    expanding: bool = False,
    minimum_coverage: float = 0.8,
    positive_only: bool = True,
    timings: dict | None = None,
) -> list[pd.Series]:
    """Batch exact midranks, including host preparation and synchronous download.

    CuPy is deliberately optional. No automatic CPU fallback hides a failed GPU
    validation, and no caller should use this backend without benchmark evidence.
    """
    import cupy as cp

    tick = time.perf_counter()
    if years < 1 or not 0 < minimum_coverage <= 1:
        raise ValueError("invalid percentile configuration")
    arrays, boundaries, ready_masks, sizes = [], [], [], []
    offset = 0
    for series in observations:
        index = series.index
        if (
            not isinstance(index, pd.DatetimeIndex)
            or not index.is_unique
            or not index.is_monotonic_increasing
        ):
            raise ValueError("unique increasing DatetimeIndex required")
        values = series.to_numpy(dtype=np.float64, copy=True)
        valid = np.isfinite(values)
        if positive_only:
            valid &= values > 0
        values[~valid] = np.nan
        ready = np.zeros(len(values), dtype=np.uint8)
        if valid.any():
            first = index[np.flatnonzero(valid)[0]]
            ready = (valid & (index >= first + pd.DateOffset(years=years))).astype(np.uint8)
        left = (
            np.zeros(len(values), dtype=np.int64)
            if expanding
            else index.searchsorted(index - pd.DateOffset(years=years)).astype(np.int64)
        )
        arrays.append(values)
        boundaries.append(left + offset)
        ready_masks.append(ready)
        sizes.append(len(values))
        offset += len(values)
    if not offset:
        return [pd.Series(np.nan, index=s.index, dtype=float) for s in observations]
    if timings is not None:
        timings["host_prepare_seconds"] = time.perf_counter() - tick
        tick = time.perf_counter()
    device_values = cp.asarray(np.concatenate(arrays))
    device_left = cp.asarray(np.concatenate(boundaries))
    device_ready = cp.asarray(np.concatenate(ready_masks))
    if timings is not None:
        cp.cuda.get_current_stream().synchronize()
        timings["h2d_seconds"] = time.perf_counter() - tick
        timings["h2d_bytes"] = offset * 17
        tick = time.perf_counter()
    result = cp.empty(offset, dtype=cp.float64)
    kernel = cp.RawKernel(
        _KERNEL, "midrank", options=("--fmad=false", "--prec-div=true", "--std=c++17")
    )
    kernel(
        ((offset + 127) // 128,),
        (128,),
        (
            device_values,
            device_left,
            device_ready,
            np.int64(offset),
            np.int64(int(252 * years * minimum_coverage)),
            result,
        ),
    )
    cp.cuda.get_current_stream().synchronize()
    if timings is not None:
        timings["kernel_allocation_and_sync_seconds"] = time.perf_counter() - tick
        tick = time.perf_counter()
    host = cp.asnumpy(result)  # blocking result retrieval is part of the public call
    if timings is not None:
        timings["d2h_seconds"] = time.perf_counter() - tick
        timings["d2h_bytes"] = offset * 8
    output, start = [], 0
    for series, size in zip(observations, sizes):
        output.append(pd.Series(host[start : start + size], index=series.index, dtype=float))
        start += size
    return output
