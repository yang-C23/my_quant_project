from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from quant.data.loader import load_symbol_csv, list_symbols_from_data_dir, load_symbols_from_stocklist


def _choose_data_dir(data_dir: str | None) -> Path:
    if data_dir:
        return Path(data_dir)
    clean_dir = Path("data_clean")
    if clean_dir.exists():
        return clean_dir
    return Path("data")


def _filter_symbols(symbols: list[str], exclude_boards: set[str]) -> list[str]:
    if not exclude_boards:
        return symbols

    filtered = []
    for sym in symbols:
        sym = str(sym).zfill(6)
        if "gem" in exclude_boards and sym.startswith(("300", "301")):
            continue
        if "star" in exclude_boards and sym.startswith("688"):
            continue
        if "bj" in exclude_boards and sym.startswith(("4", "8")):
            continue
        filtered.append(sym)
    return filtered


def _kdj(df: pd.DataFrame, n: int, k_period: int, d_period: int) -> pd.DataFrame:
    low_n = df["low"].rolling(n, min_periods=n).min()
    high_n = df["high"].rolling(n, min_periods=n).max()
    denom = (high_n - low_n).replace(0, np.nan)
    rsv = (df["close"] - low_n) / denom * 100.0
    rsv = rsv.fillna(0.0)
    k = rsv.rolling(k_period, min_periods=k_period).mean()
    d = k.rolling(d_period, min_periods=d_period).mean()
    j = k * 3.0 - d * 2.0
    return pd.DataFrame({"rsv": rsv, "k": k, "d": d, "j": j})


def _regime_labels(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    sma_120 = df["close"].rolling(120, min_periods=120).mean()
    regime = pd.Series("neutral", index=df.index)
    regime = regime.mask(df["close"] > sma_120, "bull")
    regime = regime.mask(df["close"] < sma_120, "bear")

    vol = df["close"].pct_change().rolling(20, min_periods=20).std()
    vol_q = vol.quantile([0.33, 0.66])
    vol_regime = pd.Series("mid", index=df.index)
    if not vol_q.empty:
        vol_regime = vol_regime.mask(vol <= vol_q.iloc[0], "low")
        vol_regime = vol_regime.mask(vol >= vol_q.iloc[1], "high")
    return regime, vol_regime


def _net_return(entry: pd.Series, exit_: pd.Series, buy_cost: float, sell_cost: float) -> pd.Series:
    return exit_ * (1.0 - sell_cost) / (entry * (1.0 + buy_cost)) - 1.0


def build_returns(
    symbol: str,
    df: pd.DataFrame,
    horizons: Iterable[int],
    kdj_n: int,
    kdj_k: int,
    kdj_d: int,
    j_threshold: float,
    buy_cost: float,
    sell_cost: float,
    filter_limit: bool,
) -> pd.DataFrame:
    df = df.copy()
    df = df.sort_values("date").reset_index(drop=True)
    kdj = _kdj(df, n=kdj_n, k_period=kdj_k, d_period=kdj_d)
    df = pd.concat([df, kdj], axis=1)

    signal = df["j"] < j_threshold
    entry_open = df["open"].shift(-1)
    entry_date = df["date"].shift(-1)

    regime, vol_regime = _regime_labels(df)
    regime = regime.where(signal)
    vol_regime = vol_regime.where(signal)

    entry_ok = entry_open.notna()
    if filter_limit:
        if "is_upper_limit" in df.columns:
            entry_ok &= ~df["is_upper_limit"].shift(-1).fillna(False)
        if "is_suspended" in df.columns:
            entry_ok &= ~df["is_suspended"].shift(-1).fillna(False)

    base_mask = signal & entry_ok
    if not base_mask.any():
        return pd.DataFrame()

    rows = []
    for h in sorted(set(int(x) for x in horizons)):
        exit_close = df["close"].shift(-(1 + h))
        valid = base_mask & exit_close.notna()
        if not valid.any():
            continue
        ret = _net_return(entry_open, exit_close, buy_cost, sell_cost)
        out = pd.DataFrame(
            {
                "symbol": symbol,
                "signal_date": df.loc[valid, "date"].values,
                "entry_date": entry_date.loc[valid].values,
                "horizon": h,
                "return": ret.loc[valid].values,
                "regime": regime.loc[valid].values,
                "vol_regime": vol_regime.loc[valid].values,
            }
        )
        rows.append(out)

    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def _summary_stats(values: pd.Series) -> dict:
    vals = values.dropna().astype(float)
    if vals.empty:
        return {
            "count": 0,
            "win_rate": 0.0,
            "avg_return": 0.0,
            "median_return": 0.0,
            "p25_return": 0.0,
            "p75_return": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "profit_factor": 0.0,
        }

    wins = vals[vals > 0]
    losses = vals[vals <= 0]
    profit_factor = wins.sum() / abs(losses.sum()) if losses.sum() < 0 else float("inf")
    return {
        "count": int(len(vals)),
        "win_rate": float((vals > 0).mean()),
        "avg_return": float(vals.mean()),
        "median_return": float(vals.median()),
        "p25_return": float(vals.quantile(0.25)),
        "p75_return": float(vals.quantile(0.75)),
        "avg_win": float(wins.mean()) if not wins.empty else 0.0,
        "avg_loss": float(losses.mean()) if not losses.empty else 0.0,
        "profit_factor": float(profit_factor) if np.isfinite(profit_factor) else 0.0,
    }


def summarize(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.copy()
    df["signal_id"] = df["symbol"].astype(str) + "_" + pd.to_datetime(df["signal_date"]).dt.strftime("%Y%m%d")

    def agg(group: pd.DataFrame) -> pd.Series:
        stats = _summary_stats(group["return"])
        stats["signals"] = int(group["signal_id"].nunique())
        return pd.Series(stats)

    summary = df.groupby(group_cols, dropna=False).apply(agg).reset_index()
    return summary


def write_report(df: pd.DataFrame, output_dir: Path, prefix: str, name: str) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{prefix}_{name}.csv"
    md_path = output_dir / f"{prefix}_{name}.md"
    df.to_csv(csv_path, index=False)
    md_path.write_text(df.to_markdown(index=False), encoding="utf-8")
    return {"csv": csv_path, "md": md_path}


def plot_outputs(df: pd.DataFrame, output_dir: Path, prefix: str) -> list[Path]:
    if df.empty:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    overall = df.copy()
    overall = overall.sort_values("horizon")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    axes[0].bar(overall["horizon"].astype(str), overall["win_rate"], color="#2c7fb8")
    axes[0].set_title("Win Rate by Horizon")
    axes[0].set_ylim(0, 1)
    axes[0].set_ylabel("Win Rate")

    axes[1].bar(overall["horizon"].astype(str), overall["avg_return"], color="#7fcdbb")
    axes[1].set_title("Average Return by Horizon")
    axes[1].set_ylabel("Avg Return")

    fig.tight_layout()
    path = output_dir / f"{prefix}_overall_bars.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    paths.append(path)

    return paths


def plot_yearly(df: pd.DataFrame, output_dir: Path, prefix: str) -> list[Path]:
    if df.empty:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    fig, ax = plt.subplots(figsize=(10, 5))
    for horizon, grp in df.groupby("horizon"):
        grp = grp.sort_values("year")
        ax.plot(grp["year"], grp["avg_return"], marker="o", label=f"H{horizon}")

    ax.set_title("Yearly Average Return by Horizon")
    ax.set_xlabel("Year")
    ax.set_ylabel("Avg Return")
    ax.legend()
    fig.tight_layout()

    path = output_dir / f"{prefix}_yearly_avg_return.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    paths.append(path)
    return paths


def plot_return_distribution(df: pd.DataFrame, output_dir: Path, prefix: str) -> list[Path]:
    if df.empty:
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    horizons = sorted(df["horizon"].unique())[:3]
    fig, axes = plt.subplots(1, len(horizons), figsize=(5 * len(horizons), 4))
    if len(horizons) == 1:
        axes = [axes]

    for ax, h in zip(axes, horizons):
        vals = df.loc[df["horizon"] == h, "return"]
        ax.hist(vals, bins=40, color="#fdae61", alpha=0.8)
        ax.set_title(f"Return Distribution H{h}")
        ax.set_xlabel("Return")
        ax.set_ylabel("Count")

    fig.tight_layout()
    path = output_dir / f"{prefix}_return_distribution.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    paths.append(path)
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="KDJ B1 analysis with T+1 entry")
    parser.add_argument("--data-dir", default="", help="Base data directory (default: data_clean if exists)")
    parser.add_argument("--stocklist", default="stocklist.csv", help="CSV with symbol/ts_code")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols")
    parser.add_argument("--max-stocks", type=int, default=0, help="Limit number of symbols")
    parser.add_argument(
        "--exclude-boards",
        nargs="*",
        default=["star"],
        choices=["gem", "star", "bj"],
    )
    parser.add_argument("--start", default="", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default="", help="End date YYYY-MM-DD")
    parser.add_argument("--kdj-n", type=int, default=9)
    parser.add_argument("--kdj-k", type=int, default=3)
    parser.add_argument("--kdj-d", type=int, default=3)
    parser.add_argument("--j-threshold", type=float, default=0.0)
    parser.add_argument("--horizons", default="1,3,5,10,20")
    parser.add_argument("--buy-commission", type=float, default=0.0003)
    parser.add_argument("--sell-commission", type=float, default=0.0003)
    parser.add_argument("--stamp-tax", type=float, default=0.001)
    parser.add_argument("--filter-limit", action="store_true")
    parser.add_argument("--output-dir", default="backtest_results")
    parser.add_argument("--prefix", default="")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_dir = _choose_data_dir(args.data_dir)
    horizons = tuple(int(h) for h in args.horizons.split(",") if h.strip())
    buy_cost = args.buy_commission
    sell_cost = args.sell_commission + args.stamp_tax

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = load_symbols_from_stocklist(args.stocklist, limit=args.max_stocks)
    symbols = _filter_symbols(symbols, set(args.exclude_boards or []))
    if args.max_stocks > 0:
        symbols = symbols[: args.max_stocks]
    if not symbols:
        raise SystemExit("No symbols found after filtering")

    rows = []
    for symbol in symbols:
        try:
            df = load_symbol_csv(symbol, data_dir=data_dir, start=args.start or None, end=args.end or None)
        except Exception:
            continue
        if df.empty or len(df) < max(horizons) + 2:
            continue
        out = build_returns(
            symbol=symbol,
            df=df,
            horizons=horizons,
            kdj_n=args.kdj_n,
            kdj_k=args.kdj_k,
            kdj_d=args.kdj_d,
            j_threshold=args.j_threshold,
            buy_cost=buy_cost,
            sell_cost=sell_cost,
            filter_limit=args.filter_limit,
        )
        if not out.empty:
            rows.append(out)

    if not rows:
        raise SystemExit("No signal returns found")

    full = pd.concat(rows, ignore_index=True)
    full["entry_date"] = pd.to_datetime(full["entry_date"])
    full["year"] = full["entry_date"].dt.year

    output_dir = Path(args.output_dir)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = args.prefix or f"kdj_b1_j{args.j_threshold:g}_{timestamp}"

    overall = summarize(full, ["horizon"])
    yearly = summarize(full, ["year", "horizon"])
    regime = summarize(full, ["regime", "horizon"])
    vol_regime = summarize(full, ["vol_regime", "horizon"])

    outputs = {
        "overall": write_report(overall, output_dir, prefix, "overall"),
        "yearly": write_report(yearly, output_dir, prefix, "yearly"),
        "regime": write_report(regime, output_dir, prefix, "regime"),
        "vol_regime": write_report(vol_regime, output_dir, prefix, "vol_regime"),
    }

    plot_outputs(overall, output_dir, prefix)
    plot_yearly(yearly, output_dir, prefix)
    plot_return_distribution(full, output_dir, prefix)

    print("Analysis complete")
    for name, paths in outputs.items():
        print(f"- {name}: {paths['csv']}")


if __name__ == "__main__":
    main()
