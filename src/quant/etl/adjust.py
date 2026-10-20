"""Adjustment-factor derivation from daily bars and TDX GBBQ events."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

_XDXR_COLUMNS = ["fenhong", "peigu", "songzhuangu", "peigujia"]


def _read_staging_table(staging_dir: Path, name: str) -> pd.DataFrame:
    directory = staging_dir / name
    if directory.exists():
        return pd.read_parquet(directory)
    file_path = staging_dir / f"{name}.parquet"
    if file_path.exists():
        return pd.read_parquet(file_path)
    raise FileNotFoundError(f"missing staging table: {directory} or {file_path}")


def _last_positive(values: pd.Series) -> float:
    positive = values[values > 0]
    return float(positive.iloc[-1]) if not positive.empty else 0.0


def xdxr_events(gbbq: pd.DataFrame, *, mapping: str = "tdx") -> pd.DataFrame:
    """Map raw category=1 GBBQ c1..c4 columns to ex-right fields.

    Physical order: c1 cash per 10, c2 subscription price, c3 bonus per 10,
    c4 rights per 10. ``legacy_swapped_rights`` exists only for old result replay.
    """
    if gbbq.empty:
        return pd.DataFrame(columns=["symbol", "date", *_XDXR_COLUMNS])

    events = gbbq.loc[gbbq["category"].eq(1), ["symbol", "date", "c1", "c2", "c3", "c4"]].copy()
    if events.empty:
        return pd.DataFrame(columns=["symbol", "date", *_XDXR_COLUMNS])
    events["date"] = pd.to_datetime(events["date"])
    if mapping not in {"tdx", "legacy_swapped_rights"}:
        raise ValueError("unknown corporate-action mapping")
    quantity_col, price_col = ("c4", "c2") if mapping == "tdx" else ("c2", "c4")
    grouped = (
        events.sort_values(["symbol", "date"])
        .groupby(["symbol", "date"], sort=True)
        .agg(
            fenhong=("c1", "sum"),
            peigu=(quantity_col, "sum"),
            songzhuangu=("c3", "sum"),
            peigujia=(price_col, _last_positive),
        )
        .reset_index()
    )
    return grouped


def theoretical_preclose(prev_close: pd.Series, ev: pd.DataFrame) -> pd.Series:
    """Return QUANTAXIS theoretical pre-close for ex-right events.

    Formula from v1 ``calc_basic.py``:
    ``(prev_close * 10 - fenhong + peigu * peigujia) / (10 + songzhuangu + peigu)``.
    Missing event fields are treated as zero, so non-event rows equal
    ``prev_close``.
    """
    event = ev.reindex(columns=_XDXR_COLUMNS).fillna(0.0)
    fenhong = event["fenhong"].astype(float)
    peigu = event["peigu"].astype(float)
    songzhuangu = event["songzhuangu"].astype(float)
    peigujia = event["peigujia"].astype(float)
    denom = 10.0 + songzhuangu + peigu
    numer = prev_close.astype(float) * 10.0 - fenhong + peigu * peigujia
    return (numer / denom).where(denom != 0, prev_close.astype(float))


def daily_with_preclose(
    daily: pd.DataFrame, gbbq: pd.DataFrame, *, mapping: str = "tdx"
) -> pd.DataFrame:
    """Attach v1-compatible theoretical ``preclose`` and XDXR marker columns."""
    required = {"symbol", "date", "close"}
    missing = required - set(daily.columns)
    if missing:
        raise KeyError(f"daily missing required columns: {sorted(missing)}")

    frame = daily.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values(["symbol", "date"]).reset_index(drop=True)
    frame["prev_close"] = frame.groupby("symbol", sort=False)["close"].shift(1)

    events = xdxr_events(gbbq, mapping=mapping)
    frame = frame.merge(events, on=["symbol", "date"], how="left")
    frame["has_xdxr"] = frame[_XDXR_COLUMNS].notna().any(axis=1)
    event_cols = frame[_XDXR_COLUMNS].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    frame["preclose"] = theoretical_preclose(frame["prev_close"], event_cols)
    first_bar = frame["prev_close"].isna()
    frame.loc[first_bar, "preclose"] = frame.loc[first_bar, "close"].astype(float)
    frame["preclose"] = frame["preclose"].round(4)
    return frame


def compute_adjust(
    daily: pd.DataFrame, gbbq: pd.DataFrame, *, mapping: str = "tdx"
) -> pd.DataFrame:
    """Compute multiplicative HFQ and derived QFQ factors.

    On ex-right rows, v1 multiplies the running HFQ factor by
    ``prev_close_actual / preclose_theoretical``. ``qfq_factor`` is the
    multiplicative normalized factor with the latest row equal to 1.
    """
    frame = daily_with_preclose(daily[["symbol", "date", "close"]], gbbq, mapping=mapping)
    ratio = np.where(
        frame["has_xdxr"] & frame["preclose"].gt(0) & frame["prev_close"].notna(),
        frame["prev_close"].astype(float) / frame["preclose"].astype(float),
        1.0,
    )
    frame["hfq_factor"] = pd.Series(ratio, index=frame.index).groupby(frame["symbol"]).cumprod()
    frame["hfq_factor"] = frame["hfq_factor"].round(8)
    latest = frame.groupby("symbol", sort=False)["hfq_factor"].transform("last")
    frame["qfq_factor"] = frame["hfq_factor"] / latest
    frame["date"] = frame["date"].dt.date
    return frame[["symbol", "date", "hfq_factor", "qfq_factor"]]


def build_adjust_staging(staging_dir: Path) -> int:
    """Build ``staging/adjust.parquet`` from daily and gbbq staging tables."""
    from quant.data.snapshots import assert_unsealed

    assert_unsealed(staging_dir)
    daily = _read_staging_table(staging_dir, "daily")
    gbbq = _read_staging_table(staging_dir, "gbbq")
    adjust = compute_adjust(daily, gbbq)
    adjust.to_parquet(staging_dir / "adjust.parquet", index=False, compression="zstd")
    return len(adjust)
