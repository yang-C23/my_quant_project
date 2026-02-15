from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd


def _build_rows(results: Iterable[dict], horizons: Iterable[int]) -> list[dict]:
    rows: list[dict] = []
    for item in results:
        symbol = item["symbol"]
        signal_count = item.get("signal_count", 0)
        horizon_stats = item.get("horizon_stats", {})
        for h in horizons:
            stats = horizon_stats.get(h)
            if stats is None:
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "signals": signal_count,
                    "horizon": h,
                    "count": stats.count,
                    "win_rate": stats.win_rate,
                    "avg_return": stats.avg_return,
                    "median_return": stats.median_return,
                    "p25_return": stats.p25_return,
                    "p75_return": stats.p75_return,
                }
            )
    return rows


def summarize_results(results: list[dict], horizons: Iterable[int]) -> pd.DataFrame:
    rows = _build_rows(results, horizons)
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    return df.sort_values(["symbol", "horizon"]).reset_index(drop=True)


def summarize_overall(results: list[dict], horizons: Iterable[int]) -> pd.DataFrame:
    horizon_returns: dict[int, list[float]] = {int(h): [] for h in horizons}
    signal_counts = 0
    for item in results:
        signal_counts += int(item.get("signal_count", 0))
        returns = item.get("returns", {})
        for h, vals in returns.items():
            if h in horizon_returns:
                horizon_returns[h].extend(list(vals))

    rows = []
    for h in horizons:
        vals = pd.Series(horizon_returns.get(h, []), dtype=float)
        if vals.empty:
            rows.append(
                {
                    "symbol": "ALL",
                    "signals": signal_counts,
                    "horizon": h,
                    "count": 0,
                    "win_rate": 0.0,
                    "avg_return": 0.0,
                    "median_return": 0.0,
                    "p25_return": 0.0,
                    "p75_return": 0.0,
                }
            )
            continue

        rows.append(
            {
                "symbol": "ALL",
                "signals": signal_counts,
                "horizon": h,
                "count": int(len(vals)),
                "win_rate": float((vals > 0).mean()),
                "avg_return": float(vals.mean()),
                "median_return": float(vals.median()),
                "p25_return": float(vals.quantile(0.25)),
                "p75_return": float(vals.quantile(0.75)),
            }
        )

    return pd.DataFrame(rows)


def write_report(df: pd.DataFrame, output_dir: str | Path, prefix: str) -> dict:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    csv_path = output_path / f"{prefix}_summary.csv"
    md_path = output_path / f"{prefix}_summary.md"

    df.to_csv(csv_path, index=False)
    md_path.write_text(df.to_markdown(index=False), encoding="utf-8")

    return {"csv": csv_path, "md": md_path}
