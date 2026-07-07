"""In-sample parameter scans for R1 research tasks."""

from __future__ import annotations

import itertools
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from quant.config import load_config
from quant.data.api import get_ohlcv
from quant.data.universe import list_symbols
from quant.research.forward_returns import run_event_study
from quant.research.ic import rank_ic

IS_START = pd.Timestamp("2015-01-01")
IS_END_LIMIT = pd.Timestamp("2021-12-31")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SignalBuilder = Callable[[str, pd.DataFrame, Mapping[str, Any]], pd.Series]
PriceLoader = Callable[[str, str | None, str | None], pd.DataFrame]


@dataclass(frozen=True)
class ResearchConfig:
    """Configuration for one IS-only research scan."""

    name: str
    signal: str
    grid: dict[str, tuple[Any, ...]]
    baseline: dict[str, Any]
    is_start: str = IS_START.date().isoformat()
    is_end: str = IS_END_LIMIT.date().isoformat()
    horizons: tuple[int, ...] = (1, 3, 5, 10, 20)
    objective: str = "h5_avg_x_profit_factor"
    ic: bool = False
    universe: str = "stocks_nostar"
    symbols: tuple[str, ...] = ()
    max_symbols: int | None = None
    exclude_boards: frozenset[str] = frozenset({"star", "b"})
    entry_filters: str = "ashare"
    regime_by: str | None = None
    warmup_days: int = 0
    report_dir: str = "backtest_results/research"
    min_signals_per_year: float = 30.0
    stability_metric: str = "h5_avg"
    stability_floor: float = 0.7

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, default_name: str = "research") -> "ResearchConfig":
        """Build and validate a research config mapping."""
        _reject_post_is_dates(data)
        grid = {
            str(key): tuple(values if isinstance(values, list | tuple) else [values])
            for key, values in dict(data.get("grid") or {}).items()
        }
        baseline = {str(key): value for key, value in dict(data.get("baseline") or {}).items()}
        if not grid:
            raise ValueError("research config requires a non-empty grid")
        if not baseline:
            raise ValueError("research config requires baseline params")

        is_start = str(data.get("is_start", IS_START.date().isoformat()))
        is_end = str(data.get("is_end", IS_END_LIMIT.date().isoformat()))
        _validate_is_window(is_start, is_end)

        symbols = tuple(str(item) for item in (data.get("symbols") or ()))
        exclude_boards = frozenset(str(item) for item in data.get("exclude_boards", ["star", "b"]))
        horizons = tuple(int(item) for item in data.get("horizons", (1, 3, 5, 10, 20)))
        if not horizons or any(item <= 0 for item in horizons):
            raise ValueError("horizons must be positive")
        return cls(
            name=str(data.get("name") or default_name),
            signal=str(data["signal"]),
            grid=grid,
            baseline=baseline,
            is_start=is_start,
            is_end=is_end,
            horizons=tuple(sorted(set(horizons))),
            objective=str(data.get("objective", "h5_avg_x_profit_factor")),
            ic=bool(data.get("ic", False)),
            universe=str(data.get("universe", "stocks_nostar")),
            symbols=symbols,
            max_symbols=(
                int(data["max_symbols"]) if data.get("max_symbols") is not None else None
            ),
            exclude_boards=exclude_boards,
            entry_filters=str(data.get("entry_filters", "ashare")),
            regime_by=data.get("regime_by"),
            warmup_days=int(data.get("warmup_days", 0)),
            report_dir=str(data.get("report_dir", "backtest_results/research")),
            min_signals_per_year=float(data.get("min_signals_per_year", 30.0)),
            stability_metric=str(data.get("stability_metric", "h5_avg")),
            stability_floor=float(data.get("stability_floor", 0.7)),
        )


@dataclass(frozen=True)
class ScanResult:
    """Outcome of a parameter scan."""

    table: pd.DataFrame
    top: pd.DataFrame
    baseline: pd.Series


def load_research_config(path: str | Path) -> ResearchConfig:
    """Load a YAML/JSON research config and enforce IS-only bounds."""
    config_path = Path(path)
    return ResearchConfig.from_mapping(load_config(config_path), default_name=config_path.stem)


def _reject_post_is_dates(value: Any, *, trail: str = "config") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_post_is_dates(item, trail=f"{trail}.{key}")
        return
    if isinstance(value, list | tuple):
        for idx, item in enumerate(value):
            _reject_post_is_dates(item, trail=f"{trail}[{idx}]")
        return
    if isinstance(value, str) and _DATE_RE.match(value):
        if pd.Timestamp(value) > IS_END_LIMIT:
            raise ValueError(f"{trail} exceeds IS end {IS_END_LIMIT.date().isoformat()}")


def _validate_is_window(start: str, end: str) -> None:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if start_ts > end_ts:
        raise ValueError("is_start must be <= is_end")
    if end_ts > IS_END_LIMIT:
        raise ValueError(f"is_end exceeds IS end {IS_END_LIMIT.date().isoformat()}")


def _param_product(grid: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    keys = list(grid)
    return [dict(zip(keys, combo, strict=True)) for combo in itertools.product(*(grid[k] for k in keys))]


def _default_signal_builder(name: str, bars: pd.DataFrame, params: Mapping[str, Any]) -> pd.Series:
    if name == "kdj_oversold" and "j_threshold" in params:
        from quant.indicators.kdj import kdj

        return (kdj(bars)["j"] < float(params["j_threshold"])).fillna(False).astype(bool)

    from quant.signals import registry

    func = registry.get(name)
    try:
        signal = func(bars, **dict(params))  # type: ignore[misc]
    except TypeError:
        signal = func(bars)
    return signal.fillna(False).astype(bool)


def _load_symbol_prices(symbol: str, start: str | None, end: str | None) -> pd.DataFrame:
    qfq = get_ohlcv(
        symbol,
        start=start,
        end=end,
        adjust="qfq",
        fields=("open", "high", "low", "close", "volume", "amount", "factor", "float_mktcap"),
    )
    raw = get_ohlcv(
        symbol,
        start=start,
        end=end,
        adjust="raw",
        fields=("open", "suspended", "limit_up_price"),
    ).rename(columns={"open": "raw_open", "suspended": "is_suspended"})
    frame = qfq.join(raw, how="left")
    frame["symbol"] = symbol
    return frame.reset_index()


def _load_prices_cached(
    symbols: Sequence[str],
    start: str,
    end: str,
    *,
    warmup_days: int,
    price_loader: PriceLoader,
) -> dict[str, pd.DataFrame]:
    load_start = (
        (pd.Timestamp(start) - pd.Timedelta(days=warmup_days)).date().isoformat()
        if warmup_days > 0
        else start
    )
    cache: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        try:
            frame = price_loader(symbol, load_start, end)
        except ValueError:
            continue
        if not frame.empty:
            frame = frame.copy()
            frame["date"] = pd.to_datetime(frame["date"])
            cache[symbol] = frame.sort_values("date").reset_index(drop=True)
    if not cache:
        raise ValueError("no price data loaded for research scan")
    return cache


def _resolve_symbols(cfg: ResearchConfig) -> list[str]:
    if cfg.symbols:
        symbols = list(cfg.symbols)
    else:
        symbols = list_symbols(exclude_boards=set(cfg.exclude_boards), at=None)
    if cfg.max_symbols is not None:
        symbols = symbols[: cfg.max_symbols]
    if not symbols:
        raise ValueError("research config resolved to an empty symbol universe")
    return symbols


def _signals_for_params(
    cfg: ResearchConfig,
    price_cache: Mapping[str, pd.DataFrame],
    params: Mapping[str, Any],
    signal_builder: SignalBuilder,
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    is_start = pd.Timestamp(cfg.is_start)
    for symbol, frame in price_cache.items():
        indexed = frame.set_index("date", drop=False)
        signal = signal_builder(cfg.signal, indexed, params).reindex(indexed.index).fillna(False)
        signal = signal[pd.to_datetime(signal.index) >= is_start]
        rows.append(
            pd.DataFrame(
                {"symbol": symbol, "date": pd.to_datetime(signal.index), "sig": signal.to_numpy(bool)}
            )
        )
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["symbol", "date", "sig"])


def _prices_frame(price_cache: Mapping[str, pd.DataFrame], cfg: ResearchConfig) -> pd.DataFrame:
    start = pd.Timestamp(cfg.is_start)
    frames = [frame[frame["date"] >= start].copy() for frame in price_cache.values()]
    return pd.concat(frames, ignore_index=True).sort_values(["symbol", "date"]).reset_index(drop=True)


def _factor_from_signals(signals: pd.DataFrame, name: str) -> pd.Series:
    if signals.empty:
        return pd.Series(dtype=float, name=name)
    frame = signals.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame[name] = frame["sig"].astype(float)
    return frame.set_index(["date", "symbol"])[name].sort_index()


def _profit_factor(values: pd.Series) -> float:
    gains = values[values > 0].sum()
    losses = values[values < 0].sum()
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / abs(losses))


def _years(start: str, end: str) -> float:
    days = max((pd.Timestamp(end) - pd.Timestamp(start)).days + 1, 1)
    return days / 365.25


def _summarize_scan_row(
    cfg: ResearchConfig,
    params: Mapping[str, Any],
    events: pd.DataFrame,
    pooled: pd.DataFrame,
    signal_count: int,
    rank_ic_5: float | None,
    icir_5: float | None,
) -> dict[str, Any]:
    row: dict[str, Any] = dict(params)
    row["signals"] = int(signal_count)
    row["signals_per_year"] = signal_count / _years(cfg.is_start, cfg.is_end)
    pooled_by_h = pooled.set_index("horizon") if not pooled.empty else pd.DataFrame()
    for horizon in cfg.horizons:
        prefix = f"h{horizon}"
        if not pooled_by_h.empty and horizon in pooled_by_h.index:
            stats = pooled_by_h.loc[horizon]
            row[f"{prefix}_count"] = int(stats["count"])
            row[f"{prefix}_avg"] = float(stats["avg_return"])
            row[f"{prefix}_win"] = float(stats["win_rate"])
            row[f"{prefix}_profit_factor"] = float(stats["profit_factor"])
        else:
            row[f"{prefix}_count"] = 0
            row[f"{prefix}_avg"] = np.nan
            row[f"{prefix}_win"] = np.nan
            row[f"{prefix}_profit_factor"] = np.nan
    for regime_value in (0, 1):
        key = f"regime{regime_value}_h5_avg"
        subset = events[(events.get("horizon") == 5) & (events.get("regime") == regime_value)]
        row[key] = float(subset["return"].mean()) if not subset.empty else np.nan
    row["rank_ic_5"] = rank_ic_5
    row["icir_5"] = icir_5
    row["objective_value"] = _objective_value(row, cfg.objective)
    row["density_ok"] = bool(row["signals_per_year"] >= cfg.min_signals_per_year)
    return row


def _objective_value(row: Mapping[str, Any], objective: str) -> float:
    if objective == "h5_avg_x_profit_factor":
        return float(row.get("h5_avg", np.nan)) * float(row.get("h5_profit_factor", np.nan))
    if objective == "profit_factor_h5":
        return float(row.get("h5_profit_factor", np.nan))
    if objective in row:
        return float(row[objective])
    raise ValueError(f"unsupported objective: {objective}")


def _amv_regime(price_loader: PriceLoader, cfg: ResearchConfig) -> pd.Series | None:
    if cfg.regime_by != "amv":
        return None
    from quant.indicators.amv import amv, amv_timing_signal

    try:
        index_frame = price_loader("sh999999", cfg.is_start, cfg.is_end).set_index("date")
    except ValueError:
        return None
    return amv_timing_signal(amv(index_frame))["regime"]


def run_param_scan(
    cfg: ResearchConfig,
    *,
    price_loader: PriceLoader | None = None,
    signal_builder: SignalBuilder | None = None,
) -> ScanResult:
    """Run an IS-only grid scan with one cached price load per symbol."""
    _validate_is_window(cfg.is_start, cfg.is_end)
    symbols = _resolve_symbols(cfg)
    loader = price_loader or _load_symbol_prices
    builder = signal_builder or _default_signal_builder
    price_cache = _load_prices_cached(
        symbols, cfg.is_start, cfg.is_end, warmup_days=cfg.warmup_days, price_loader=loader
    )
    prices = _prices_frame(price_cache, cfg)
    regime = _amv_regime(loader, cfg)

    def evaluate(params: Mapping[str, Any]) -> dict[str, Any]:
        signals = _signals_for_params(cfg, price_cache, params, builder)
        result = run_event_study(
            signals,
            horizons=cfg.horizons,
            start=cfg.is_start,
            end=cfg.is_end,
            prices=prices,
            regime=regime,
            entry_filters=cfg.entry_filters,  # type: ignore[arg-type]
        )
        rank_ic_5 = icir_5 = None
        if cfg.ic:
            ic = rank_ic(_factor_from_signals(signals, cfg.signal), horizon=5, prices=prices)
            rank_ic_5 = float(ic.attrs["summary"]["mean"])
            icir_5 = float(ic.attrs["summary"]["ir"])
        signal_count = int(result.pooled["signals"].max()) if not result.pooled.empty else 0
        return _summarize_scan_row(
            cfg, params, result.events, result.pooled, signal_count, rank_ic_5, icir_5
        )

    rows = [evaluate(params) for params in _param_product(cfg.grid)]
    table = pd.DataFrame(rows)
    baseline = pd.Series(evaluate(cfg.baseline), name="baseline")
    top = _top_table(table, cfg, baseline)
    return ScanResult(table=table, top=top, baseline=baseline)


def _top_table(table: pd.DataFrame, cfg: ResearchConfig, baseline: pd.Series) -> pd.DataFrame:
    top = table.sort_values("objective_value", ascending=False).head(5).copy()
    stable_values = []
    baseline_value = float(baseline.get(cfg.stability_metric, np.nan))
    for _, row in top.iterrows():
        neighbors = neighborhood_stability(
            table,
            cfg.grid,
            row,
            metric=cfg.stability_metric,
            floor=cfg.stability_floor,
            baseline_value=baseline_value,
        )
        stable_values.append(bool(neighbors.attrs.get("stable", False)))
    top["stable_neighborhood"] = stable_values
    return top.reset_index(drop=True)


def neighborhood_stability(
    table: pd.DataFrame,
    params_grid: Mapping[str, Sequence[Any]],
    best: Mapping[str, Any] | pd.Series,
    *,
    metric: str = "h5_avg",
    floor: float = 0.7,
    baseline_value: float | None = None,
) -> pd.DataFrame:
    """Return best point's +/- one-step neighbors and attach a stable flag."""
    best_map = dict(best)
    mask = pd.Series(True, index=table.index)
    strict_neighbor = pd.Series(False, index=table.index)
    for param, values in params_grid.items():
        values_list = list(values)
        if best_map.get(param) not in values_list:
            continue
        pos = values_list.index(best_map[param])
        allowed = {values_list[i] for i in range(max(0, pos - 1), min(len(values_list), pos + 2))}
        mask &= table[param].isin(allowed)
        strict_neighbor |= table[param] != best_map[param]
    neighbors = table[mask & strict_neighbor].copy()
    best_value = float(best_map.get(metric, np.nan))
    if neighbors.empty or np.isnan(best_value):
        stable = False
    else:
        metric_values = neighbors[metric].astype(float).dropna()
        floor_ok = bool((metric_values >= floor * best_value).all()) if not metric_values.empty else False
        median_ok = True
        if baseline_value is not None and not np.isnan(baseline_value):
            median_ok = bool(metric_values.median() > baseline_value)
        stable = floor_ok and median_ok
    neighbors.attrs["stable"] = stable
    neighbors.attrs["neighbor_count"] = int(len(neighbors))
    return neighbors


def write_scan_report(result: ScanResult, out_dir: str | Path, name: str) -> dict[str, Path]:
    """Write CSV and markdown scan reports."""
    output_dir = Path(out_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{name}_scan.csv"
    md_path = output_dir / f"{name}_scan.md"
    result.table.to_csv(csv_path, index=False)
    lines = [
        f"# Research Scan: {name}",
        "",
        "IS-only scan. Tier1 returns are before fees.",
        "",
        "## Baseline",
        result.baseline.to_frame("value").to_markdown(),
        "",
        "## Top 5",
        result.top.to_markdown(index=False),
        "",
        "## Grid",
        result.table.sort_values("objective_value", ascending=False).head(20).to_markdown(
            index=False
        ),
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"csv": csv_path, "md": md_path}
