"""Information coefficient and quantile analysis for qlib-style factors."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from quant.data.api import get_ohlcv
from quant.data.symbols import from_qlib


def _normalize_factor(factor: pd.Series) -> pd.Series:
    if not isinstance(factor.index, pd.MultiIndex) or factor.index.nlevels != 2:
        raise ValueError("factor index must be MultiIndex(date, instrument)")
    frame = factor.rename("factor").reset_index()
    names = list(factor.index.names)
    if names[0] in {None, "date", "datetime"}:
        frame.columns = ["date", "instrument", "factor"]
    else:
        frame.columns = ["instrument", "date", "factor"]
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.set_index(["date", "instrument"])["factor"].astype(float).sort_index()


def _normalize_prices(prices: pd.DataFrame) -> pd.DataFrame:
    frame = prices.copy()
    if isinstance(frame.index, pd.MultiIndex):
        frame = frame.reset_index()
    if "instrument" not in frame.columns and "symbol" in frame.columns:
        frame = frame.rename(columns={"symbol": "instrument"})
    missing = {"instrument", "date", "open", "close"} - set(frame.columns)
    if missing:
        raise ValueError(f"prices missing columns: {sorted(missing)}")
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.sort_values(["instrument", "date"]).reset_index(drop=True)


def _load_prices_for_factor(factor: pd.Series) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for instrument in factor.index.get_level_values("instrument").unique():
        frame = get_ohlcv(from_qlib(str(instrument)), adjust="qfq", fields=["open", "close"])
        frame = frame.reset_index()
        frame["instrument"] = instrument
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def _forward_returns(
    factor: pd.Series, horizon: int, prices: pd.DataFrame | None = None
) -> pd.DataFrame:
    factor_s = _normalize_factor(factor)
    price_frame = (
        _normalize_prices(prices) if prices is not None else _load_prices_for_factor(factor_s)
    )
    rows: list[dict] = []
    for instrument, group in price_frame.groupby("instrument", sort=True):
        group = group.reset_index(drop=True)
        positions = {pd.Timestamp(dt): pos for pos, dt in enumerate(group["date"])}
        try:
            inst_factor = factor_s.xs(instrument, level="instrument", drop_level=False)
        except KeyError:
            continue
        for (date, _), value in inst_factor.items():
            pos = positions.get(pd.Timestamp(date))
            if pos is None:
                continue
            entry_pos = pos + 1
            exit_pos = entry_pos + horizon - 1
            if exit_pos >= len(group):
                continue
            entry_open = group.iloc[entry_pos]["open"]
            exit_close = group.iloc[exit_pos]["close"]
            if pd.isna(value) or pd.isna(entry_open) or pd.isna(exit_close):
                continue
            rows.append(
                {
                    "date": pd.Timestamp(date),
                    "instrument": instrument,
                    "factor": float(value),
                    "forward_return": float(exit_close) / float(entry_open) - 1.0,
                }
            )
    return pd.DataFrame(rows)


def _summary(ic: pd.DataFrame, total_dates: int) -> dict[str, float]:
    valid = ic["ic"].dropna()
    std = float(valid.std(ddof=1)) if len(valid) > 1 else np.nan
    mean = float(valid.mean()) if len(valid) else np.nan
    return {
        "mean": mean,
        "std": std,
        "ir": mean / std if std and not np.isnan(std) else np.nan,
        "t_stat": mean / (std / np.sqrt(len(valid))) if std and not np.isnan(std) else np.nan,
        "days": int(len(valid)),
        "skipped_days": int(total_dates - len(valid)),
        "mean_n": float(ic["n"].mean()) if not ic.empty else 0.0,
    }


def rank_ic(
    factor: pd.Series,
    horizon: int = 1,
    *,
    universe: str = "nostar",
    price: str = "open_next",
    prices: pd.DataFrame | None = None,
    min_count: int = 2,
) -> pd.DataFrame:
    """Compute daily cross-sectional Spearman RankIC for factor_t."""
    if price != "open_next":
        raise ValueError("only price='open_next' is supported")
    factor_s = _normalize_factor(factor)
    aligned = _forward_returns(factor_s, int(horizon), prices)
    rows: list[dict] = []
    total_dates = int(factor_s.index.get_level_values("date").nunique())
    if aligned.empty:
        out = pd.DataFrame(columns=["date", "ic", "n", "nonzero"])
        out.attrs["summary"] = _summary(out, total_dates)
        out.attrs["sample_n_distribution"] = {}
        out.attrs["universe"] = universe
        out.attrs["horizon"] = int(horizon)
        return out
    for date, group in aligned.groupby("date", sort=True):
        n = int(len(group))
        nonzero = int((group["factor"] != 0).sum())
        if n < min_count or group["factor"].nunique() < 2 or group["forward_return"].nunique() < 2:
            rows.append({"date": date, "ic": np.nan, "n": n, "nonzero": nonzero})
            continue
        rows.append(
            {
                "date": date,
                "ic": float(group["factor"].corr(group["forward_return"], method="spearman")),
                "n": n,
                "nonzero": nonzero,
            }
        )
    out = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    out.attrs["summary"] = _summary(out, total_dates)
    out.attrs["sample_n_distribution"] = out["n"].describe().to_dict() if not out.empty else {}
    out.attrs["universe"] = universe
    out.attrs["horizon"] = int(horizon)
    return out


def ic_decay(
    factor: pd.Series,
    horizons: Sequence[int] = (1, 3, 5, 10, 20),
    *,
    prices: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return RankIC summary over multiple forward horizons."""
    rows = []
    for horizon in horizons:
        ic = rank_ic(factor, int(horizon), prices=prices)
        rows.append({"horizon": int(horizon), **ic.attrs["summary"]})
    return pd.DataFrame(rows)


def quantile_returns(
    factor: pd.Series,
    q: int = 5,
    horizon: int = 5,
    *,
    prices: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Compute per-date quantile forward returns and cumulative curves."""
    aligned = _forward_returns(factor, int(horizon), prices)
    rows: list[dict] = []
    for date, group in aligned.groupby("date", sort=True):
        if len(group) < q or group["factor"].nunique() < q:
            continue
        labels = pd.qcut(group["factor"], q, labels=False, duplicates="drop") + 1
        temp = group.assign(quantile=labels.astype(int))
        for quantile, part in temp.groupby("quantile", sort=True):
            rows.append(
                {
                    "date": date,
                    "quantile": int(quantile),
                    "mean_return": float(part["forward_return"].mean()),
                    "n": int(len(part)),
                }
            )
    out = pd.DataFrame(rows)
    if not out.empty:
        out["cum_return"] = out.groupby("quantile")["mean_return"].cumsum()
    return out


def ic_report(
    name: str,
    factor: pd.Series,
    *,
    output_dir: str | Path = "backtest_results",
    horizons: Sequence[int] = (1, 3, 5, 10, 20),
    prices: pd.DataFrame | None = None,
) -> Path:
    """Write a markdown IC report and return its path."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    decay = ic_decay(factor, horizons, prices=prices)
    ic1 = rank_ic(factor, int(horizons[0]), prices=prices)
    sample_dist = pd.Series(ic1.attrs.get("sample_n_distribution", {}), name="n")
    path = out_dir / f"{name}_ic_report.md"
    path.write_text(
        "\n".join(
            [
                f"# IC Report: {name}",
                "",
                "## Decay",
                decay.to_markdown(index=False),
                "",
                "## Daily Sample Count Distribution",
                sample_dist.to_markdown(),
                "",
                "Sparse boolean factors can have too few active names per day; "
                "interpret RankIC with the nonzero distribution before promoting a signal.",
            ]
        ),
        encoding="utf-8",
    )
    return path
