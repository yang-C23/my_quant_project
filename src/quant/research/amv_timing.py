"""IS-only timing research for the 0AMV index regime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant.config import load_config
from quant.data.api import get_ohlcv
from quant.indicators.amv import amv, amv_timing_signal
from quant.research.optimize import IS_END_LIMIT, IS_START, _reject_post_is_dates

VARIANTS = ("immediate", "confirm_life", "confirm_2d", "confirm_break")


@dataclass(frozen=True)
class TimingStats:
    """Regime timing performance summary."""

    cumulative_return: float
    annual_return: float
    max_drawdown: float
    exposure: float
    switches_per_year: float
    wave_count: int
    win_rate: float
    profit_factor: float
    avg_wave_return: float
    median_wave_return: float
    wave_returns: tuple[float, ...]


@dataclass(frozen=True)
class AmvResearchResult:
    """AMV timing scan output."""

    table: pd.DataFrame
    top: pd.DataFrame
    baseline: pd.Series
    variant_costs: pd.DataFrame
    k_invariance: pd.DataFrame
    report_paths: dict[str, Path]


def evaluate_timing(
    amv_df: pd.DataFrame, signal_df: pd.DataFrame, index_close: pd.Series
) -> TimingStats:
    """Evaluate a regime with t signal -> t+1 close-to-close exposure."""
    del amv_df
    close = index_close.astype(float).sort_index()
    regime = signal_df["regime"].reindex(close.index).fillna(0).astype(int)
    position = regime.shift(1).fillna(0).astype(int)
    daily_return = close.pct_change(fill_method=None).fillna(0.0)
    strategy_return = daily_return * position
    equity = (1.0 + strategy_return).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    waves = _wave_returns(position, strategy_return)
    years = max((close.index[-1] - close.index[0]).days + 1, 1) / 365.25
    cumulative = float(equity.iloc[-1] - 1.0)
    annual = (1.0 + cumulative) ** (1.0 / years) - 1.0 if cumulative > -1.0 else -1.0
    switches = int(position.diff().abs().fillna(0).sum())
    return TimingStats(
        cumulative_return=cumulative,
        annual_return=float(annual),
        max_drawdown=float(drawdown.min()),
        exposure=float(position.mean()),
        switches_per_year=float(switches / years),
        wave_count=len(waves),
        win_rate=float(np.mean(np.array(waves) > 0)) if waves else np.nan,
        profit_factor=_profit_factor(pd.Series(waves, dtype=float)),
        avg_wave_return=float(np.mean(waves)) if waves else np.nan,
        median_wave_return=float(np.median(waves)) if waves else np.nan,
        wave_returns=tuple(float(item) for item in waves),
    )


def build_variant_signal(
    amv_df: pd.DataFrame,
    index_close: pd.Series,
    *,
    buy_th: float,
    sell_th: float,
    variant: str,
) -> pd.DataFrame:
    """Build one AMV timing variant."""
    base = amv_timing_signal(amv_df, buy_th=buy_th, sell_th=sell_th)
    buy = base["sig_amv_buy"].copy()
    sell = base["sig_amv_sell"].copy()
    if variant == "immediate":
        confirmed_buy = buy
    elif variant == "confirm_life":
        confirmed_buy = buy & (amv_df["amv_close"] > amv_df["amv_life"])
    elif variant == "confirm_2d":
        confirmed_buy = buy.shift(1, fill_value=False) & (amv_df["amv_pct"] > 0)
    elif variant == "confirm_break":
        prior_high = index_close.astype(float).rolling(10).max().shift(1)
        confirmed_buy = buy & (index_close.astype(float) > prior_high)
    else:
        raise ValueError(f"unknown AMV variant: {variant}")
    return _signals_from_triggers(confirmed_buy.fillna(False), sell.fillna(False))


def verify_k_invariance(index_df: pd.DataFrame, k_values: list[float]) -> pd.DataFrame:
    """Show that multiplicative K does not change AMV pct signals."""
    base = amv(index_df, k=k_values[0])["amv_pct"]
    rows = []
    for k_value in k_values:
        pct = amv(index_df, k=k_value)["amv_pct"]
        rows.append(
            {
                "k": float(k_value),
                "max_abs_pct_diff": float((pct - base).abs().max(skipna=True)),
            }
        )
    return pd.DataFrame(rows)


def run_amv_research(config_path: str | Path) -> AmvResearchResult:
    """Run the 0AMV IS timing scan and write reports."""
    cfg_path = Path(config_path)
    raw_cfg = load_config(cfg_path)
    _reject_post_is_dates(raw_cfg)
    name = str(raw_cfg.get("name", cfg_path.stem))
    start = str(raw_cfg.get("is_start", IS_START.date().isoformat()))
    end = str(raw_cfg.get("is_end", IS_END_LIMIT.date().isoformat()))
    _validate_window(start, end)
    symbol = str(raw_cfg.get("symbol", "sh999999"))
    k_grid = _grid_values(raw_cfg.get("k_grid", {"start": 1.8, "stop": 2.6, "step": 0.05}))
    buy_values = _grid_values(raw_cfg.get("buy_th", {"start": 2.5, "stop": 6.0, "step": 0.5}))
    sell_values = [
        float(item) for item in raw_cfg.get("sell_th", [-4.0, -3.5, -3.0, -2.5, -2.3, -2.0, -1.5])
    ]
    variants = tuple(str(item) for item in raw_cfg.get("variants", VARIANTS))
    baseline_params = dict(
        raw_cfg.get(
            "baseline",
            {"k": 2.13, "buy_th": 4.0, "sell_th": -2.3, "variant": "immediate"},
        )
    )
    report_dir = Path(str(raw_cfg.get("report_dir", "backtest_results/research")))

    index_df = get_ohlcv(
        symbol,
        start=start,
        end=end,
        adjust="qfq",
        fields=("open", "high", "low", "close", "volume", "amount"),
    )
    k_invariance = verify_k_invariance(index_df, k_grid)
    rows = []
    variant_cost_rows = []
    base_amv = amv(index_df, k=float(baseline_params["k"]))
    base_signal = build_variant_signal(
        base_amv,
        index_df["close"],
        buy_th=float(baseline_params["buy_th"]),
        sell_th=float(baseline_params["sell_th"]),
        variant="immediate",
    )
    baseline = _row_for_params(
        index_df,
        k=float(baseline_params["k"]),
        buy_th=float(baseline_params["buy_th"]),
        sell_th=float(baseline_params["sell_th"]),
        variant=str(baseline_params["variant"]),
    )
    for buy_th in buy_values:
        for sell_th in sell_values:
            immediate_signal = build_variant_signal(
                base_amv, index_df["close"], buy_th=buy_th, sell_th=sell_th, variant="immediate"
            )
            for variant in variants:
                row = _row_for_params(
                    index_df,
                    k=float(baseline_params["k"]),
                    buy_th=buy_th,
                    sell_th=sell_th,
                    variant=variant,
                )
                rows.append(row)
                if variant != "immediate":
                    variant_cost_rows.append(
                        {
                            "buy_th": buy_th,
                            "sell_th": sell_th,
                            "variant": variant,
                            **right_side_cost(
                                immediate_signal,
                                build_variant_signal(
                                    base_amv,
                                    index_df["close"],
                                    buy_th=buy_th,
                                    sell_th=sell_th,
                                    variant=variant,
                                ),
                                index_df["close"],
                            ),
                        }
                    )
    table = pd.DataFrame(rows)
    top = _stable_top(table, pd.Series(baseline), metric="cumulative_return")
    variant_costs = pd.DataFrame(variant_cost_rows)
    paths = write_amv_report(
        name=name,
        table=table,
        top=top,
        baseline=pd.Series(baseline),
        variant_costs=variant_costs,
        k_invariance=k_invariance,
        report_dir=report_dir,
        base_stats=evaluate_timing(base_amv, base_signal, index_df["close"]),
    )
    return AmvResearchResult(
        table=table,
        top=top,
        baseline=pd.Series(baseline),
        variant_costs=variant_costs,
        k_invariance=k_invariance,
        report_paths=paths,
    )


def right_side_cost(
    immediate_signal: pd.DataFrame, variant_signal: pd.DataFrame, index_close: pd.Series
) -> dict[str, float]:
    """Compare delayed confirmation entries against immediate entries."""
    close = index_close.astype(float)
    base_entries = _entry_dates(immediate_signal)
    variant_entries = _entry_dates(variant_signal)
    base_exits = _exit_dates(immediate_signal)
    missed: list[float] = []
    avoided_false = 0
    for entry_date in base_entries:
        exit_candidates = [item for item in base_exits if item > entry_date]
        exit_date = exit_candidates[0] if exit_candidates else close.index[-1]
        matches = [item for item in variant_entries if entry_date <= item <= exit_date]
        base_return = float(close.loc[exit_date] / close.loc[entry_date] - 1.0)
        if matches:
            missed.append(float(close.loc[matches[0]] / close.loc[entry_date] - 1.0))
        elif base_return <= 0:
            avoided_false += 1
    base_stats = evaluate_timing(pd.DataFrame(index=close.index), immediate_signal, close)
    variant_stats = evaluate_timing(pd.DataFrame(index=close.index), variant_signal, close)
    return {
        "base_entries": float(len(base_entries)),
        "confirmed_entries": float(len(variant_entries)),
        "missed_return_avg": float(np.mean(missed)) if missed else np.nan,
        "avoided_false": float(avoided_false),
        "win_rate_delta": float(variant_stats.win_rate - base_stats.win_rate),
    }


def write_amv_report(
    *,
    name: str,
    table: pd.DataFrame,
    top: pd.DataFrame,
    baseline: pd.Series,
    variant_costs: pd.DataFrame,
    k_invariance: pd.DataFrame,
    report_dir: Path,
    base_stats: TimingStats,
) -> dict[str, Path]:
    """Write AMV timing CSV and markdown reports."""
    report_dir.mkdir(parents=True, exist_ok=True)
    csv_path = report_dir / f"{name}_scan.csv"
    md_path = report_dir / f"{name}_scan.md"
    table.to_csv(csv_path, index=False)
    variant_summary = (
        table.groupby("variant", as_index=False)
        .agg(
            rows=("variant", "size"),
            best_cumulative_return=("cumulative_return", "max"),
            median_cumulative_return=("cumulative_return", "median"),
            median_wave_count=("wave_count", "median"),
        )
        .sort_values("best_cumulative_return", ascending=False)
    )
    lines = [
        f"# AMV Timing Research: {name}",
        "",
        "IS-only timing scan. Returns are before fees.",
        "",
        "## K Invariance",
        k_invariance.to_markdown(index=False),
        "",
        "## Baseline",
        baseline.to_frame("value").to_markdown(),
        "",
        "## Immediate Baseline Waves",
        pd.Series(
            {
                "wave_count": base_stats.wave_count,
                "avg_wave_return": base_stats.avg_wave_return,
                "median_wave_return": base_stats.median_wave_return,
                "switches_per_year": base_stats.switches_per_year,
            }
        ).to_markdown(),
        "",
        "## Top 5",
        top.to_markdown(index=False),
        "",
        "## Variants",
        variant_summary.to_markdown(index=False),
        "",
        "## Right-Side Cost",
        variant_costs.head(20).to_markdown(index=False),
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"csv": csv_path, "md": md_path}


def _row_for_params(
    index_df: pd.DataFrame, *, k: float, buy_th: float, sell_th: float, variant: str
) -> dict[str, Any]:
    amv_df = amv(index_df, k=k)
    signal = build_variant_signal(
        amv_df, index_df["close"], buy_th=buy_th, sell_th=sell_th, variant=variant
    )
    stats = evaluate_timing(amv_df, signal, index_df["close"])
    return {
        "k": float(k),
        "buy_th": float(buy_th),
        "sell_th": float(sell_th),
        "variant": variant,
        "cumulative_return": stats.cumulative_return,
        "annual_return": stats.annual_return,
        "max_drawdown": stats.max_drawdown,
        "exposure": stats.exposure,
        "switches_per_year": stats.switches_per_year,
        "wave_count": stats.wave_count,
        "win_rate": stats.win_rate,
        "profit_factor": stats.profit_factor,
        "avg_wave_return": stats.avg_wave_return,
        "median_wave_return": stats.median_wave_return,
    }


def _signals_from_triggers(buy: pd.Series, sell: pd.Series) -> pd.DataFrame:
    holding = 0
    regime: list[int] = []
    for buy_now, sell_now in zip(buy.astype(bool), sell.astype(bool), strict=True):
        if sell_now:
            holding = 0
        elif buy_now:
            holding = 1
        regime.append(holding)
    return pd.DataFrame(
        {
            "sig_amv_buy": buy.astype(bool),
            "sig_amv_sell": sell.astype(bool),
            "regime": pd.Series(regime, index=buy.index, dtype="int8"),
        },
        index=buy.index,
    )


def _wave_returns(position: pd.Series, strategy_return: pd.Series) -> list[float]:
    waves: list[float] = []
    active: list[float] = []
    for held, ret in zip(position.astype(bool), strategy_return.astype(float), strict=True):
        if held:
            active.append(float(ret))
            continue
        if active:
            waves.append(float(np.prod(np.array(active) + 1.0) - 1.0))
            active = []
    if active:
        waves.append(float(np.prod(np.array(active) + 1.0) - 1.0))
    return waves


def _entry_dates(signal: pd.DataFrame) -> list[pd.Timestamp]:
    regime = signal["regime"].astype(int)
    return list(regime.index[(regime.eq(1)) & (regime.shift(1).fillna(0).eq(0))])


def _exit_dates(signal: pd.DataFrame) -> list[pd.Timestamp]:
    regime = signal["regime"].astype(int)
    return list(regime.index[(regime.eq(0)) & (regime.shift(1).fillna(0).eq(1))])


def _profit_factor(values: pd.Series) -> float:
    gains = values[values > 0].sum()
    losses = values[values < 0].sum()
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / abs(losses))


def _grid_values(spec: Any) -> list[float]:
    if isinstance(spec, list | tuple):
        return [float(item) for item in spec]
    start = float(spec["start"])
    stop = float(spec["stop"])
    step = float(spec["step"])
    count = int(round((stop - start) / step))
    return [round(start + i * step, 10) for i in range(count + 1)]


def _stable_top(table: pd.DataFrame, baseline: pd.Series, *, metric: str) -> pd.DataFrame:
    top = table.sort_values(metric, ascending=False).head(5).copy()
    stable = []
    for _, row in top.iterrows():
        same_variant = table[table["variant"].eq(row["variant"])]
        buy_neighbors = same_variant["buy_th"].sub(float(row["buy_th"])).abs().le(0.5)
        sell_neighbors = same_variant["sell_th"].sub(float(row["sell_th"])).abs().le(0.5)
        neighbors = same_variant[buy_neighbors & sell_neighbors]
        neighbors = neighbors[
            ~(neighbors["buy_th"].eq(row["buy_th"]) & neighbors["sell_th"].eq(row["sell_th"]))
        ]
        metric_values = neighbors[metric].astype(float).dropna()
        floor_ok = (
            bool((metric_values >= 0.7 * float(row[metric])).all()) if len(metric_values) else False
        )
        median_ok = (
            bool(metric_values.median() > float(baseline[metric])) if len(metric_values) else False
        )
        stable.append(floor_ok and median_ok)
    top["stable_neighborhood"] = stable
    return top.reset_index(drop=True)


def _validate_window(start: str, end: str) -> None:
    if pd.Timestamp(start) > pd.Timestamp(end):
        raise ValueError("is_start must be <= is_end")
    if pd.Timestamp(end) > IS_END_LIMIT:
        raise ValueError(f"is_end exceeds IS end {IS_END_LIMIT.date().isoformat()}")
