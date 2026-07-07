"""Paired entry/exit studies for holding-style signals."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from quant.config import load_config
from quant.data.api import get_ohlcv
from quant.data.universe import list_symbols
from quant.indicators.dual_trend import dual_trend
from quant.research.optimize import IS_END_LIMIT, IS_START, _reject_post_is_dates


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
    stop_loss: float | None = None,
) -> PairStudyResult:
    """Evaluate entry signal -> next-open entry -> first exit-rule next-open exit."""
    if max_hold <= 0:
        raise ValueError("max_hold must be positive")
    signals = _normalize_signal(entry_sig, "entry")
    exits = {name: _normalize_signal(rule, name) for name, rule in exit_rules.items()}
    px = _normalize_prices(prices)
    exclusions = {"entry_missing": 0, "entry_filtered": 0, "exit_missing": 0}
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
            entry_pos = _next_tradable_pos(bars, signal_pos + 1, entry_filters=entry_filters)
            if entry_pos is None:
                exclusions["entry_missing"] += 1
                continue
            if entry_filters == "ashare" and _blocked_entry(bars.iloc[entry_pos]):
                exclusions["entry_filtered"] += 1
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
    symbols = list_symbols(exclude_boards=set(raw.get("exclude_boards", ["star", "b"])), at=None)
    if max_symbols is not None:
        symbols = symbols[: int(max_symbols)]
    load_start = (pd.Timestamp(start) - pd.Timedelta(days=warmup_days)).date().isoformat()
    frames = []
    entry_frames: dict[str, list[pd.DataFrame]] = {"golden_cross": [], "dual_entry": []}
    exit_frames: dict[str, list[pd.DataFrame]] = {
        "dead_cross": [],
        "close_lt_white_2d": [],
        "close_lt_yellow": [],
    }
    for symbol in symbols:
        try:
            frame = _load_prices(symbol, load_start, end)
        except ValueError:
            continue
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
        entry_frames["dual_entry"].append(_signal_frame(symbol, dt.index, dt["sig_dual_trend_entry"]))
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
    return _write_dual_report(name, matrix, fake, Path(str(raw.get("report_dir", "backtest_results/research"))))


def _exit_trade(
    *,
    symbol: str,
    signal_pos: int,
    entry_pos: int,
    bars: pd.DataFrame,
    exits: dict[str, pd.DataFrame],
    positions: dict[pd.Timestamp, int],
    max_hold: int,
    stop_loss: float | None,
) -> dict[str, Any] | None:
    entry_row = bars.iloc[entry_pos]
    entry_price = float(entry_row["open"])
    stop_price = entry_price * (1.0 - stop_loss) if stop_loss is not None else None
    exit_signal_pos = None
    exit_reason = None
    last_signal_pos = min(len(bars) - 2, entry_pos + max_hold - 1)
    for pos in range(entry_pos, last_signal_pos + 1):
        row = bars.iloc[pos]
        if stop_price is not None and float(row["low"]) <= stop_price:
            exit_signal_pos = pos
            exit_reason = "stop_loss"
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
    exit_exec_pos = _next_tradable_pos(bars, exit_signal_pos + 1, entry_filters="none")
    if exit_exec_pos is None:
        return None
    exit_row = bars.iloc[exit_exec_pos]
    exit_price = float(exit_row["open"])
    held = bars.iloc[entry_pos : exit_signal_pos + 1]
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
        "mae": float(held["low"].min() / entry_price - 1.0),
        "mfe": float(held["high"].max() / entry_price - 1.0),
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
    if "raw_open" not in frame.columns:
        frame["raw_open"] = frame["open"]
    return frame.sort_values(["symbol", "date"]).reset_index(drop=True)


def _next_tradable_pos(
    bars: pd.DataFrame, start_pos: int, *, entry_filters: Literal["ashare", "none"]
) -> int | None:
    for pos in range(start_pos, len(bars)):
        row = bars.iloc[pos]
        if pd.isna(row["open"]) or bool(row.get("is_suspended", False)):
            continue
        if entry_filters == "ashare" and _blocked_entry(row):
            return pos
        return pos
    return None


def _blocked_entry(row: pd.Series) -> bool:
    limit_up = row.get("limit_up_price", np.nan)
    return bool(pd.notna(limit_up) and pd.notna(row.get("raw_open", np.nan)) and row["raw_open"] >= limit_up)


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


def _load_prices(symbol: str, start: str, end: str) -> pd.DataFrame:
    qfq = get_ohlcv(
        symbol,
        start=start,
        end=end,
        adjust="qfq",
        fields=("open", "high", "low", "close", "volume", "amount"),
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


def _signal_frame(symbol: str, index: pd.Index, values: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({"symbol": symbol, "date": pd.to_datetime(index), "sig": values.to_numpy(bool)})


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
            near_dead = any(pd.Timestamp(bars.iloc[i]["date"]) in dead_dates for i in range(pos + 1, min(len(bars), pos + days + 1)))
            rows.append(near_dead)
    values = pd.Series(rows, dtype=bool)
    return pd.Series({"golden_crosses": int(len(values)), "fake_ratio_5d": float(values.mean()) if len(values) else np.nan})


def _write_dual_report(name: str, matrix: pd.DataFrame, fake: pd.Series, report_dir: Path) -> dict[str, Path]:
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


def _validate_window(start: str, end: str) -> None:
    if pd.Timestamp(start) > pd.Timestamp(end):
        raise ValueError("is_start must be <= is_end")
    if pd.Timestamp(end) > IS_END_LIMIT:
        raise ValueError(f"is_end exceeds IS end {IS_END_LIMIT.date().isoformat()}")
