"""Paired entry/exit studies for holding-style signals."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from quant.config import load_config
from quant.data.api import get_ohlcv_batch
from quant.data.universe import list_symbols
from quant.indicators.brick_osc import PRESETS as BRICK_PRESETS
from quant.indicators.brick_osc import brick_osc
from quant.indicators.dual_trend import dual_trend
from quant.indicators.volume_patterns import single_needle_proxy
from quant.research.optimize import IS_END_LIMIT, IS_START, _reject_post_is_dates, sample_symbols

StopLoss = float | Literal["entry_low"]


@dataclass(frozen=True)
class PairStudyResult:
    """Trade-pair study output."""

    trades: pd.DataFrame
    summary: pd.DataFrame
    exclusions: dict[str, int]


def run_pair_study(
    entry_sig: pd.DataFrame | pd.Series,
    exit_rules: dict[str, pd.DataFrame | pd.Series],
    prices: pd.DataFrame,
    *,
    entry_filters: Literal["ashare", "none"] = "ashare",
    max_hold: int = 120,
    stop_loss: StopLoss | None = None,
    two_day_no_profit: bool = False,
) -> PairStudyResult:
    """Evaluate entry signal -> next-open entry -> first exit-rule next-open exit."""
    if max_hold <= 0:
        raise ValueError("max_hold must be positive")
    signals = _normalize_signal(entry_sig, "entry")
    exits = {name: _normalize_signal(rule, name) for name, rule in exit_rules.items()}
    px = _normalize_prices(prices)
    exclusions = {
        "entry_missing": 0,
        "entry_suspended": 0,
        "entry_limit_up": 0,
        "exit_missing": 0,
    }
    rows: list[dict[str, Any]] = []
    for symbol, bars in px.groupby("symbol", sort=True):
        bars = bars.reset_index(drop=True)
        positions = {pd.Timestamp(dt): pos for pos, dt in enumerate(bars["date"])}
        symbol_entries = signals[signals["symbol"].eq(symbol)]
        next_available_entry_pos = 0
        for entry in symbol_entries.itertuples(index=False):
            signal_pos = positions.get(pd.Timestamp(entry.date))
            if signal_pos is None or signal_pos < next_available_entry_pos:
                continue
            entry_pos = signal_pos + 1
            if entry_pos >= len(bars):
                exclusions["entry_missing"] += 1
                continue
            entry_row = bars.iloc[entry_pos]
            if entry_filters == "ashare":
                if bool(entry_row.get("is_suspended", False)) or pd.isna(entry_row["open"]):
                    exclusions["entry_suspended"] += 1
                    continue
                if _blocked_entry(entry_row):
                    exclusions["entry_limit_up"] += 1
                    continue
            elif pd.isna(entry_row["open"]):
                exclusions["entry_missing"] += 1
                continue
            trade = _exit_trade(
                symbol=symbol,
                signal_pos=signal_pos,
                entry_pos=entry_pos,
                bars=bars,
                exits={name: frame[frame["symbol"].eq(symbol)] for name, frame in exits.items()},
                positions=positions,
                max_hold=max_hold,
                stop_loss=stop_loss,
                two_day_no_profit=two_day_no_profit,
            )
            if trade is None:
                exclusions["exit_missing"] += 1
                continue
            rows.append(trade)
            next_available_entry_pos = int(trade["exit_exec_pos"]) + 1
    trades = pd.DataFrame(rows)
    return PairStudyResult(trades=trades, summary=_summary(trades), exclusions=exclusions)


def run_dual_trend_research(config_path: str | Path) -> dict[str, Path]:
    """Run the dual-trend pair matrix and write reports."""
    cfg_path = Path(config_path)
    raw = load_config(cfg_path)
    _reject_post_is_dates(raw)
    name = str(raw.get("name", cfg_path.stem))
    start = str(raw.get("is_start", IS_START.date().isoformat()))
    end = str(raw.get("is_end", IS_END_LIMIT.date().isoformat()))
    _validate_window(start, end)
    warmup_days = int(raw.get("warmup_days", 180))
    max_symbols = raw.get("max_symbols")
    seed = int(raw.get("sample_seed", 42))
    symbols = list_symbols(exclude_boards=set(raw.get("exclude_boards", ["star", "b"])), at=None)
    symbols = sample_symbols(symbols, int(max_symbols) if max_symbols is not None else None, seed)
    load_start = (pd.Timestamp(start) - pd.Timedelta(days=warmup_days)).date().isoformat()
    frames = []
    entry_frames: dict[str, list[pd.DataFrame]] = {"golden_cross": [], "dual_entry": []}
    exit_frames: dict[str, list[pd.DataFrame]] = {
        "dead_cross": [],
        "close_lt_white_2d": [],
        "close_lt_yellow": [],
    }
    all_prices = _load_prices_batch(symbols, load_start, end)
    for symbol, frame in all_prices.groupby("symbol", sort=True):
        frame = frame.reset_index(drop=True)
        dt = dual_trend(frame.set_index("date"))
        trade_frame = frame[frame["date"].ge(pd.Timestamp(start))].copy()
        frames.append(trade_frame)
        dt = dt.loc[dt.index >= pd.Timestamp(start)]
        close = trade_frame.set_index("date")["close"].reindex(dt.index)
        white = dt["white"]
        yellow = dt["yellow"]
        lt_white = close < white
        exit_frames["dead_cross"].append(_signal_frame(symbol, dt.index, dt["sig_dead_cross"]))
        exit_frames["close_lt_white_2d"].append(
            _signal_frame(symbol, dt.index, lt_white & lt_white.shift(1, fill_value=False))
        )
        exit_frames["close_lt_yellow"].append(_signal_frame(symbol, dt.index, close < yellow))
        entry_frames["golden_cross"].append(_signal_frame(symbol, dt.index, dt["sig_golden_cross"]))
        entry_frames["dual_entry"].append(
            _signal_frame(symbol, dt.index, dt["sig_dual_trend_entry"])
        )
    prices = pd.concat(frames, ignore_index=True)
    entries = {name: pd.concat(parts, ignore_index=True) for name, parts in entry_frames.items()}
    exits = {name: pd.concat(parts, ignore_index=True) for name, parts in exit_frames.items()}
    matrix_rows = []
    study_specs = [
        ("dead_cross", {"dead_cross": exits["dead_cross"]}, None),
        ("close_lt_white_2d", {"close_lt_white_2d": exits["close_lt_white_2d"]}, None),
        ("close_lt_yellow", {"close_lt_yellow": exits["close_lt_yellow"]}, None),
        ("stop_8", {}, 0.08),
        ("dead_cross_stop_8", {"dead_cross": exits["dead_cross"]}, 0.08),
    ]
    for entry_name, entry_signal in entries.items():
        for exit_name, exit_rules, stop in study_specs:
            result = run_pair_study(
                entry_signal,
                exit_rules,
                prices,
                max_hold=int(raw.get("max_hold", 120)),
                stop_loss=stop,
            )
            row = result.summary.iloc[0].to_dict() if not result.summary.empty else _empty_summary()
            matrix_rows.append({"entry": entry_name, "exit": exit_name, **row})
    matrix = pd.DataFrame(matrix_rows)
    fake = _fake_golden_cross(entries["golden_cross"], exits["dead_cross"], prices)
    return _write_dual_report(
        name, matrix, fake, Path(str(raw.get("report_dir", "backtest_results/research")))
    )


def run_shortterm_research(config_path: str | Path) -> dict[str, Path]:
    """Run brick/single-needle short-term hold/stop matrix."""
    cfg_path = Path(config_path)
    raw = load_config(cfg_path)
    _reject_post_is_dates(raw)
    name = str(raw.get("name", cfg_path.stem))
    start = str(raw.get("is_start", IS_START.date().isoformat()))
    end = str(raw.get("is_end", IS_END_LIMIT.date().isoformat()))
    _validate_window(start, end)
    warmup_days = int(raw.get("warmup_days", 180))
    max_symbols = raw.get("max_symbols")
    seed = int(raw.get("sample_seed", 42))
    symbols = list_symbols(exclude_boards=set(raw.get("exclude_boards", ["star", "b"])), at=None)
    symbols = sample_symbols(symbols, int(max_symbols) if max_symbols is not None else None, seed)
    load_start = (pd.Timestamp(start) - pd.Timedelta(days=warmup_days)).date().isoformat()
    prices, entries = _shortterm_inputs(symbols, load_start, end, pd.Timestamp(start))
    rows = []
    holds = [int(item) for item in raw.get("max_hold_grid", [1, 2, 3, 4, 6])]
    stops = list(raw.get("stop_grid", ["entry_low", 0.02, 0.03, "none"]))
    single_trades: dict[tuple[int, str], pd.Series] = {}
    for entry_name, signal in entries.items():
        for hold in holds:
            for stop in stops:
                stop_value = _coerce_stop_value(str(stop))
                result = run_pair_study(
                    signal,
                    {},
                    prices,
                    max_hold=hold,
                    stop_loss=stop_value,
                    two_day_no_profit=bool(raw.get("two_day_no_profit", True)),
                )
                summary = result.summary.iloc[0].to_dict()
                rows.append({"entry": entry_name, "max_hold": hold, "stop": str(stop), **summary})
                if entry_name == "single_needle_proxy":
                    single_trades[(hold, str(stop))] = result.trades["return"].astype(float)
    matrix = pd.DataFrame(rows)
    single_prior = _single_prior_bootstrap(matrix, single_trades)
    gem_compare = pd.DataFrame()
    if bool(raw.get("gem_exclusion_check", True)) and not matrix.empty:
        exclude = set(raw.get("exclude_boards", ["star", "b"])) | {"gem"}
        no_gem_symbols = list_symbols(exclude_boards=exclude, at=None)
        no_gem_symbols = sample_symbols(
            no_gem_symbols, int(max_symbols) if max_symbols is not None else None, seed
        )
        no_gem_prices, no_gem_entries = _shortterm_inputs(
            no_gem_symbols, load_start, end, pd.Timestamp(start)
        )
        gem_rows = []
        for item in matrix.sort_values("profit_factor", ascending=False).head(2).itertuples():
            result = run_pair_study(
                no_gem_entries[str(item.entry)],
                {},
                no_gem_prices,
                max_hold=int(item.max_hold),
                stop_loss=_coerce_stop_value(str(item.stop)),
                two_day_no_profit=bool(raw.get("two_day_no_profit", True)),
            )
            summary = result.summary.iloc[0].to_dict()
            gem_rows.append(
                {
                    "entry": item.entry,
                    "max_hold": int(item.max_hold),
                    "stop": str(item.stop),
                    **summary,
                }
            )
        gem_compare = pd.DataFrame(gem_rows)
    return _write_shortterm_report(
        name,
        matrix,
        single_prior,
        gem_compare,
        Path(str(raw.get("report_dir", "backtest_results/research"))),
    )


def _exit_trade(
    *,
    symbol: str,
    signal_pos: int,
    entry_pos: int,
    bars: pd.DataFrame,
    exits: dict[str, pd.DataFrame],
    positions: dict[pd.Timestamp, int],
    max_hold: int,
    stop_loss: StopLoss | None,
    two_day_no_profit: bool,
) -> dict[str, Any] | None:
    entry_row = bars.iloc[entry_pos]
    entry_price = float(entry_row["open"])
    if stop_loss == "entry_low":
        stop_price = float(entry_row["low"])
    elif stop_loss is not None:
        stop_price = entry_price * (1.0 - float(stop_loss))
    else:
        stop_price = None
    exit_signal_pos = None
    exit_reason = None
    last_signal_pos = min(len(bars) - 2, entry_pos + max_hold - 1)
    for pos in range(entry_pos, last_signal_pos + 1):
        row = bars.iloc[pos]
        # "entry_low" 语义=跌破买入 bar 低点（严格 <，否则入场日 low<=own low 恒真、
        # 全部交易退化为次日开盘卖出）；数值止损保留 <=（入场日盘中触及即有效）。
        stop_hit = stop_price is not None and (
            float(row["low"]) < stop_price
            if stop_loss == "entry_low"
            else float(row["low"]) <= stop_price
        )
        if stop_hit:
            exit_signal_pos = pos
            exit_reason = "stop_loss"
            break
        if two_day_no_profit and pos - entry_pos == 2 and float(row["close"]) <= entry_price:
            exit_signal_pos = pos
            exit_reason = "two_day_no_profit"
            break
        matched = [
            name
            for name, rule in exits.items()
            if _signal_true_on(rule, symbol, pd.Timestamp(row["date"]))
        ]
        if matched:
            exit_signal_pos = pos
            exit_reason = matched[0]
            break
        if pos == last_signal_pos:
            exit_signal_pos = pos
            exit_reason = "max_hold"
            break
    if exit_signal_pos is None or exit_reason is None:
        return None
    exit_exec_pos = _next_tradable_pos(
        bars,
        exit_signal_pos + 1,
        block_limit_down=True,
    )
    if exit_exec_pos is None:
        return None
    exit_row = bars.iloc[exit_exec_pos]
    exit_price = float(exit_row["open"])
    held = bars.iloc[entry_pos:exit_exec_pos]
    return {
        "symbol": symbol,
        "signal_date": pd.Timestamp(bars.iloc[signal_pos]["date"]),
        "entry_date": pd.Timestamp(entry_row["date"]),
        "exit_signal_date": pd.Timestamp(bars.iloc[exit_signal_pos]["date"]),
        "exit_date": pd.Timestamp(exit_row["date"]),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "return": exit_price / entry_price - 1.0,
        "hold_days": int(exit_signal_pos - entry_pos + 1),
        "exit_reason": exit_reason,
        "mae": float(min(held["low"].min(), exit_price) / entry_price - 1.0),
        "mfe": float(max(held["high"].max(), exit_price) / entry_price - 1.0),
        "exit_exec_pos": int(exit_exec_pos),
    }


def _normalize_signal(signal: pd.DataFrame | pd.Series, value_name: str) -> pd.DataFrame:
    if isinstance(signal, pd.Series):
        frame = signal.rename(value_name).reset_index()
    else:
        frame = signal.copy()
        if isinstance(frame.index, pd.MultiIndex) or "date" not in frame.columns:
            frame = frame.reset_index()
    if value_name not in frame.columns:
        candidates = [col for col in frame.columns if col not in {"symbol", "date", "index"}]
        if len(candidates) != 1:
            raise ValueError(f"{value_name} signal must have one value column")
        frame = frame.rename(columns={candidates[0]: value_name})
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.sort_values(["symbol", "date"])
    return frame[["symbol", "date", value_name]].loc[lambda x: x[value_name].astype(bool)]


def _normalize_prices(prices: pd.DataFrame) -> pd.DataFrame:
    frame = prices.copy()
    if isinstance(frame.index, pd.MultiIndex) or "date" not in frame.columns:
        frame = frame.reset_index()
    frame["date"] = pd.to_datetime(frame["date"])
    if "is_suspended" not in frame.columns:
        frame["is_suspended"] = False
    if "limit_up_price" not in frame.columns:
        frame["limit_up_price"] = np.nan
    if "limit_down_price" not in frame.columns:
        frame["limit_down_price"] = np.nan
    if "raw_open" not in frame.columns:
        frame["raw_open"] = frame["open"]
    return frame.sort_values(["symbol", "date"]).reset_index(drop=True)


def _next_tradable_pos(
    bars: pd.DataFrame,
    start_pos: int,
    *,
    block_limit_down: bool = False,
) -> int | None:
    for pos in range(start_pos, len(bars)):
        row = bars.iloc[pos]
        if pd.isna(row["open"]) or bool(row.get("is_suspended", False)):
            continue
        limit_down = row.get("limit_down_price", np.nan)
        if (
            block_limit_down
            and pd.notna(limit_down)
            and pd.notna(row.get("raw_open", np.nan))
            and row["raw_open"] <= limit_down
        ):
            continue
        return pos
    return None


def _blocked_entry(row: pd.Series) -> bool:
    limit_up = row.get("limit_up_price", np.nan)
    return bool(
        pd.notna(limit_up) and pd.notna(row.get("raw_open", np.nan)) and row["raw_open"] >= limit_up
    )


def _signal_true_on(rule: pd.DataFrame, symbol: str, date: pd.Timestamp) -> bool:
    matched = rule[(rule["symbol"].eq(symbol)) & (rule["date"].eq(date))]
    return not matched.empty


def _summary(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame([_empty_summary()])
    returns = trades["return"].astype(float)
    return pd.DataFrame(
        [
            {
                "trades": int(len(trades)),
                "win_rate": float((returns > 0).mean()),
                "avg_return": float(returns.mean()),
                "median_return": float(returns.median()),
                "profit_factor": _profit_factor(returns),
                "avg_hold_days": float(trades["hold_days"].mean()),
                "avg_mae": float(trades["mae"].mean()),
                "avg_mfe": float(trades["mfe"].mean()),
            }
        ]
    )


def _empty_summary() -> dict[str, float]:
    return {
        "trades": 0,
        "win_rate": np.nan,
        "avg_return": np.nan,
        "median_return": np.nan,
        "profit_factor": np.nan,
        "avg_hold_days": np.nan,
        "avg_mae": np.nan,
        "avg_mfe": np.nan,
    }


def _profit_factor(values: pd.Series) -> float:
    gains = values[values > 0].sum()
    losses = values[values < 0].sum()
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / abs(losses))


def _load_prices_batch(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    qfq = get_ohlcv_batch(
        symbols,
        start=start,
        end=end,
        adjust="qfq",
        fields=("open", "high", "low", "close", "volume", "amount"),
    )
    raw = get_ohlcv_batch(
        symbols,
        start=start,
        end=end,
        adjust="raw",
        fields=("open", "suspended", "limit_up_price", "limit_down_price"),
    ).rename(columns={"open": "raw_open", "suspended": "is_suspended"})
    if qfq.empty:
        raise ValueError("no symbols to load")
    return qfq.merge(raw, on=["symbol", "date"], how="left")


def _load_prices(symbol: str, start: str, end: str) -> pd.DataFrame:
    frame = _load_prices_batch([symbol], start, end)
    if frame.empty:
        raise ValueError(f"no OHLCV data for {symbol}")
    return frame.drop(columns=["symbol"]).set_index("date").reset_index().assign(symbol=symbol)


def _shortterm_inputs(
    symbols: list[str], load_start: str, end: str, signal_start: pd.Timestamp
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    frames = []
    entry_parts: dict[str, list[pd.DataFrame]] = {}
    brick_specs = [
        ("brick_strict", "strict"),
        ("brick_relaxed", "relaxed"),
        ("brick_len", "len_checked"),
    ]
    all_prices = _load_prices_batch(symbols, load_start, end)
    for symbol, frame in all_prices.groupby("symbol", sort=True):
        frame = frame.reset_index(drop=True)
        indexed = frame.set_index("date")
        frames.append(frame[frame["date"].ge(signal_start)].copy())
        for entry_name, preset_name in brick_specs:
            for smallup in (0.02, 0.03, 0.04):
                params = replace(BRICK_PRESETS[preset_name], smallup_pct=smallup)
                signal = brick_osc(indexed, params)[params.signal_col]
                key = f"{entry_name}_smallup_{smallup:.2f}"
                signal = signal.loc[signal.index >= signal_start]
                entry_parts.setdefault(key, []).append(_signal_frame(symbol, signal.index, signal))
        single = single_needle_proxy(indexed)["sig_single_needle"]
        single = single.loc[single.index >= signal_start]
        entry_parts.setdefault("single_needle_proxy", []).append(
            _signal_frame(symbol, single.index, single)
        )
    prices = pd.concat(frames, ignore_index=True)
    entries = {name: pd.concat(parts, ignore_index=True) for name, parts in entry_parts.items()}
    return prices, entries


def _coerce_stop_value(raw: str) -> StopLoss | None:
    if raw == "none":
        return None
    if raw == "entry_low":
        return "entry_low"
    return float(raw)


def _signal_frame(symbol: str, index: pd.Index, values: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        {"symbol": symbol, "date": pd.to_datetime(index), "sig": values.to_numpy(bool)}
    )


def _fake_golden_cross(
    golden: pd.DataFrame, dead: pd.DataFrame, prices: pd.DataFrame, *, days: int = 5
) -> pd.Series:
    rows = []
    golden = _normalize_signal(golden, "sig")
    dead = _normalize_signal(dead, "sig")
    px = _normalize_prices(prices)
    for symbol, group in golden.groupby("symbol"):
        bars = px[px["symbol"].eq(symbol)].reset_index(drop=True)
        positions = {pd.Timestamp(dt): pos for pos, dt in enumerate(bars["date"])}
        dead_dates = set(pd.to_datetime(dead[dead["symbol"].eq(symbol)]["date"]))
        for item in group.itertuples(index=False):
            pos = positions.get(pd.Timestamp(item.date))
            if pos is None:
                continue
            near_dead = any(
                pd.Timestamp(bars.iloc[i]["date"]) in dead_dates
                for i in range(pos + 1, min(len(bars), pos + days + 1))
            )
            rows.append(near_dead)
    values = pd.Series(rows, dtype=bool)
    return pd.Series(
        {
            "golden_crosses": int(len(values)),
            "fake_ratio_5d": float(values.mean()) if len(values) else np.nan,
        }
    )


def _write_dual_report(
    name: str, matrix: pd.DataFrame, fake: pd.Series, report_dir: Path
) -> dict[str, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    csv_path = report_dir / f"{name}_pairs.csv"
    md_path = report_dir / f"{name}_pairs.md"
    matrix.to_csv(csv_path, index=False)
    lines = [
        f"# Dual Trend Pair Study: {name}",
        "",
        "IS-only paired trades. Returns are before fees.",
        "",
        "## Matrix",
        matrix.to_markdown(index=False),
        "",
        "## Fake Golden Cross",
        fake.to_markdown(),
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"csv": csv_path, "md": md_path}


def _single_prior_bootstrap(
    matrix: pd.DataFrame, single_trades: dict[tuple[int, str], pd.Series]
) -> pd.Series:
    single = matrix[matrix["entry"].eq("single_needle_proxy")]
    if single.empty:
        return pd.Series(dtype=float)
    best = single.sort_values("profit_factor", ascending=False).iloc[0]
    key = (int(best["max_hold"]), str(best["stop"]))
    returns = single_trades.get(key, pd.Series(dtype=float)).dropna().to_numpy()
    if len(returns) == 0:
        return pd.Series(dtype=float)
    rng = np.random.default_rng(7)
    win_rates = []
    profit_factors = []
    for _ in range(1000):
        sample = rng.choice(returns, size=len(returns), replace=True)
        sample_s = pd.Series(sample)
        win_rates.append(float((sample_s > 0).mean()))
        profit_factors.append(_profit_factor(sample_s))
    return pd.Series(
        {
            "max_hold": int(best["max_hold"]),
            "stop": str(best["stop"]),
            "trades": int(len(returns)),
            "win_rate": float((returns > 0).mean()),
            "win_ci_low": float(np.quantile(win_rates, 0.025)),
            "win_ci_high": float(np.quantile(win_rates, 0.975)),
            "profit_factor": _profit_factor(pd.Series(returns)),
            "pf_ci_low": float(np.quantile(profit_factors, 0.025)),
            "pf_ci_high": float(np.quantile(profit_factors, 0.975)),
        }
    )


def _write_shortterm_report(
    name: str,
    matrix: pd.DataFrame,
    single_prior: pd.Series,
    gem_compare: pd.DataFrame,
    report_dir: Path,
) -> dict[str, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    csv_path = report_dir / f"{name}_shortterm.csv"
    md_path = report_dir / f"{name}_shortterm.md"
    matrix.to_csv(csv_path, index=False)
    top = matrix.sort_values("profit_factor", ascending=False).head(20)
    single = matrix[matrix["entry"].eq("single_needle_proxy")].sort_values(
        "profit_factor", ascending=False
    )
    lines = [
        f"# Short-Term Pair Study: {name}",
        "",
        "IS-only paired trades. Returns are before fees.",
        "",
        "## Top",
        top.to_markdown(index=False),
        "",
        "## Single Needle Proxy",
        single.head(10).to_markdown(index=False),
        "",
        "## Single Needle Prior Check",
        single_prior.to_markdown(),
        "",
        "## GEM Excluded Check",
        gem_compare.to_markdown(index=False),
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"csv": csv_path, "md": md_path}


def _validate_window(start: str, end: str) -> None:
    if pd.Timestamp(start) > pd.Timestamp(end):
        raise ValueError("is_start must be <= is_end")
    if pd.Timestamp(end) > IS_END_LIMIT:
        raise ValueError(f"is_end exceeds IS end {IS_END_LIMIT.date().isoformat()}")
