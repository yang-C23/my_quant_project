"""Vectorized Tier-1 forward-return event studies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

import numpy as np
import pandas as pd

from quant.data.api import get_ohlcv


@dataclass(frozen=True)
class EventStudyResult:
    """Container for event-study outputs."""

    events: pd.DataFrame
    per_symbol: pd.DataFrame
    pooled: pd.DataFrame
    by_year: pd.DataFrame
    exclusions: dict[str, int]
    horizons: tuple[int, ...]

    def to_report(self) -> str:
        """Render a compact markdown report."""
        parts = [
            "# Event Study",
            "",
            "## Pooled",
            self.pooled.to_markdown(index=False),
            "",
            "## Exclusions",
            pd.Series(self.exclusions, name="count").to_markdown(),
        ]
        if not self.by_year.empty:
            parts.extend(["", "## By Year", self.by_year.to_markdown(index=False)])
        return "\n".join(parts)


def _normalize_signals(signals: pd.DataFrame) -> pd.DataFrame:
    if isinstance(signals.index, pd.MultiIndex) and {"symbol", "date"}.issubset(
        set(signals.index.names)
    ):
        frame = signals.reset_index()
    else:
        frame = signals.reset_index(drop=False).copy()
    if "sig" not in frame.columns:
        value_cols = [col for col in frame.columns if col not in {"symbol", "date", "index"}]
        if len(value_cols) != 1:
            raise ValueError("signals must contain a 'sig' column or one signal value column")
        frame = frame.rename(columns={value_cols[0]: "sig"})
    missing = {"symbol", "date", "sig"} - set(frame.columns)
    if missing:
        raise ValueError(f"signals missing columns: {sorted(missing)}")
    frame = frame[["symbol", "date", "sig"]].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["sig"] = frame["sig"].astype(bool)
    return frame[frame["sig"]].sort_values(["symbol", "date"]).reset_index(drop=True)


def _normalize_prices(prices: pd.DataFrame) -> pd.DataFrame:
    frame = prices.copy()
    if isinstance(frame.index, pd.MultiIndex) and {"symbol", "date"}.issubset(
        set(frame.index.names)
    ):
        frame = frame.reset_index()
    missing = {"symbol", "date", "open", "close"} - set(frame.columns)
    if missing:
        raise ValueError(f"prices missing columns: {sorted(missing)}")
    frame["date"] = pd.to_datetime(frame["date"])
    if "is_suspended" not in frame.columns:
        frame["is_suspended"] = False
    if "limit_up_price" not in frame.columns:
        frame["limit_up_price"] = np.nan
    if "raw_open" not in frame.columns:
        frame["raw_open"] = frame["open"]
    return frame.sort_values(["symbol", "date"]).reset_index(drop=True)


def _load_one_price(symbol: str, start: str | None, end: str | None) -> pd.DataFrame | None:
    try:
        qfq = get_ohlcv(symbol, start=start, end=end, adjust="qfq", fields=["open", "close"])
        raw = get_ohlcv(
            symbol,
            start=start,
            end=end,
            adjust="raw",
            fields=["open", "suspended", "limit_up_price"],
        ).rename(columns={"open": "raw_open", "suspended": "is_suspended"})
    except ValueError:
        return None  # 窗口内无数据：由事件归入 entry_missing
    frame = qfq.join(raw, how="left").reset_index()
    frame["symbol"] = symbol
    return frame


def _load_prices(symbols: Sequence[str], start: str | None, end: str | None) -> pd.DataFrame:
    from concurrent.futures import ThreadPoolExecutor

    from quant.config import get_settings

    with ThreadPoolExecutor(max_workers=get_settings().etl_workers) as pool:
        frames = [
            f for f in pool.map(lambda s: _load_one_price(s, start, end), symbols) if f is not None
        ]
    if not frames:
        raise ValueError("no symbols to load")
    return pd.concat(frames, ignore_index=True)


def _profit_factor(values: pd.Series) -> float:
    gains = values[values > 0].sum()
    losses = values[values < 0].sum()
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return float(gains / abs(losses))


def _stats(rows: pd.DataFrame, group_cols: list[str], signal_counts: pd.Series) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(
            columns=[
                *group_cols,
                "signals",
                "horizon",
                "count",
                "win_rate",
                "avg_return",
                "median_return",
                "p25_return",
                "p75_return",
                "profit_factor",
            ]
        )

    out_rows: list[dict] = []
    for keys, group in rows.groupby([*group_cols, "horizon"], dropna=False, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        key_values = dict(zip([*group_cols, "horizon"], keys, strict=True))
        values = group["return"].astype(float)
        signal_key = (
            key_values[group_cols[0]] if group_cols and group_cols[0] in key_values else "ALL"
        )
        out_rows.append(
            {
                **key_values,
                "signals": int(signal_counts.get(signal_key, signal_counts.sum())),
                "count": int(values.count()),
                "win_rate": float((values > 0).mean()),
                "avg_return": float(values.mean()),
                "median_return": float(values.median()),
                "p25_return": float(values.quantile(0.25)),
                "p75_return": float(values.quantile(0.75)),
                "profit_factor": _profit_factor(values),
            }
        )
    return pd.DataFrame(out_rows)


def run_event_study(
    signals: pd.DataFrame,
    horizons: Sequence[int] = (1, 3, 5, 10, 20),
    universe: str = "nostar",
    start: str | None = None,
    end: str | None = None,
    entry: Literal["next_open"] = "next_open",
    *,
    prices: pd.DataFrame | None = None,
    regime: pd.Series | None = None,
    entry_filters: Literal["ashare", "none"] = "ashare",
) -> EventStudyResult:
    """Run a t signal -> t+1 open entry -> close(entry+h) forward-return study.

    ``ret_h = close(entry_bar + h) / open(entry_bar) - 1`` — hold h trading
    days after the entry day (v1-engine convention, backtest_platform.md §2).
    ``entry_filters="ashare"`` drops entries suspended or opening at the
    limit-up price; ``"none"`` replicates the unfiltered v1 KDJ study
    (parity mode). The ``signals`` statistic counts valid entries
    (entry bar exists and passes filters), matching v1 ``signal_count``.
    """
    if entry != "next_open":
        raise ValueError("only entry='next_open' is supported")
    horizon_tuple = tuple(sorted({int(h) for h in horizons}))
    if not horizon_tuple or any(h <= 0 for h in horizon_tuple):
        raise ValueError("horizons must be positive")

    sig = _normalize_signals(signals)
    if prices is None:
        prices = _load_prices(sig["symbol"].drop_duplicates().tolist(), start, end)
    px = _normalize_prices(prices)
    px_by_symbol = {symbol: group.reset_index(drop=True) for symbol, group in px.groupby("symbol")}
    valid_signal_counts: dict[str, int] = {}
    exclusions = {
        "entry_missing": 0,
        "entry_suspended": 0,
        "entry_limit_up": 0,
        "exit_missing": 0,
    }

    events: list[dict] = []
    for symbol, symbol_signals in sig.groupby("symbol", sort=True):
        bars = px_by_symbol.get(symbol)
        if bars is None or bars.empty:
            exclusions["entry_missing"] += len(symbol_signals)
            continue
        positions = {pd.Timestamp(dt): pos for pos, dt in enumerate(bars["date"])}
        for item in symbol_signals.itertuples(index=False):
            signal_date = pd.Timestamp(item.date)
            signal_pos = positions.get(signal_date)
            if signal_pos is None or signal_pos + 1 >= len(bars):
                exclusions["entry_missing"] += 1
                continue
            entry_pos = signal_pos + 1
            entry_row = bars.iloc[entry_pos]
            if entry_filters == "ashare":
                if bool(entry_row.get("is_suspended", False)) or pd.isna(entry_row["open"]):
                    exclusions["entry_suspended"] += 1
                    continue
                limit_up = entry_row.get("limit_up_price", np.nan)
                if (
                    pd.notna(limit_up)
                    and pd.notna(entry_row["raw_open"])
                    and entry_row["raw_open"] >= limit_up
                ):
                    exclusions["entry_limit_up"] += 1
                    continue
            elif pd.isna(entry_row["open"]):
                exclusions["entry_missing"] += 1
                continue
            valid_signal_counts[symbol] = valid_signal_counts.get(symbol, 0) + 1

            entry_open = float(entry_row["open"])
            entry_date = pd.Timestamp(entry_row["date"])
            for horizon in horizon_tuple:
                exit_pos = entry_pos + horizon
                if exit_pos >= len(bars) or pd.isna(bars.iloc[exit_pos]["close"]):
                    exclusions["exit_missing"] += 1
                    continue
                exit_row = bars.iloc[exit_pos]
                ret = float(exit_row["close"]) / entry_open - 1.0
                events.append(
                    {
                        "symbol": symbol,
                        "signal_date": signal_date,
                        "entry_date": entry_date,
                        "exit_date": pd.Timestamp(exit_row["date"]),
                        "horizon": horizon,
                        "return": ret,
                    }
                )

    signal_counts = pd.Series(valid_signal_counts, dtype=int)
    events_df = pd.DataFrame(events)
    if not events_df.empty and regime is not None:
        regime_s = regime.copy()
        regime_s.index = pd.to_datetime(regime_s.index)
        events_df["regime"] = events_df["entry_date"].map(regime_s)

    per_symbol = _stats(events_df, ["symbol"], signal_counts)
    pooled = _stats(
        events_df.assign(symbol="ALL"), ["symbol"], pd.Series({"ALL": signal_counts.sum()})
    )
    if not events_df.empty:
        by_year_input = events_df.assign(year=events_df["entry_date"].dt.year)
    else:
        by_year_input = events_df
    by_year = _stats(by_year_input, ["year"], pd.Series(dtype=int))
    return EventStudyResult(
        events=events_df,
        per_symbol=per_symbol,
        pooled=pooled,
        by_year=by_year,
        exclusions=exclusions,
        horizons=horizon_tuple,
    )
