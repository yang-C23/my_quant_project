"""Signal-level factor wrappers and universe filters."""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from quant.config import get_settings
from quant.data.api import get_ohlcv
from quant.indicators.b1 import B1Params, b1
from quant.indicators.kdj import kdj


def b1_signal_with_universe(
    df: pd.DataFrame, params: B1Params, *, min_float_mktcap: float = 50e8
) -> pd.Series:
    """Return B1 signal with optional universe-side market-cap filtering.

    The indicator itself does not implement MVOK or board exclusions. When
    ``float_mktcap`` is present, this wrapper applies ``float_mktcap >=
    min_float_mktcap``. Board filters belong to the caller's universe layer.
    """
    signal = b1(df, params)["sig_b1"]
    if "float_mktcap" not in df.columns:
        return signal
    return signal & df["float_mktcap"].astype(float).ge(min_float_mktcap).fillna(False)


def _compute_one_signal(
    name: str,
    symbol: str,
    start: str | None,
    end: str | None,
    signal_params: dict | None,
) -> pd.DataFrame:
    data = get_ohlcv(symbol, start=start, end=end, adjust="qfq")
    if name == "kdj_oversold" and signal_params and "j_threshold" in signal_params:
        signal = (kdj(data)["j"] < float(signal_params["j_threshold"])).fillna(False)
    else:
        from quant.signals import registry

        signal = registry.get(name)(data)
    return pd.DataFrame({"symbol": symbol, "date": data.index, "sig": signal.to_numpy(bool)})


def compute_signal(
    name: str,
    symbols: Sequence[str],
    start: str | None = None,
    end: str | None = None,
    *,
    signal_params: dict | None = None,
    workers: int | None = None,
) -> pd.DataFrame:
    """Compute a registered signal for many symbols."""
    if not symbols:
        return pd.DataFrame(columns=["symbol", "date", "sig"])

    max_workers = workers or get_settings().etl_workers
    frames: list[pd.DataFrame] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_compute_one_signal, name, symbol, start, end, signal_params): symbol
            for symbol in symbols
        }
        for future in as_completed(futures):
            frames.append(future.result())
    return (
        pd.concat(frames, ignore_index=True).sort_values(["symbol", "date"]).reset_index(drop=True)
    )
