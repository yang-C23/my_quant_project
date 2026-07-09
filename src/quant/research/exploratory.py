"""Exploratory continuous-factor research for R1."""

from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

from quant.config import load_config
from quant.data.api import get_ohlcv_batch
from quant.data.universe import list_symbols
from quant.research.forward_returns import run_event_study
from quant.research.ic import quantile_returns, rank_ic
from quant.research.optimize import IS_END_LIMIT, IS_START, _reject_post_is_dates, sample_symbols
from quant.signals.factors import compute_factor_frame


def run_exploratory_research(config_path: str | Path) -> dict[str, Path]:
    """Run IS exploratory factor checks and write reports."""
    cfg_path = Path(config_path)
    raw = load_config(cfg_path)
    _reject_post_is_dates(raw)
    name = str(raw.get("name", cfg_path.stem))
    start = str(raw.get("is_start", IS_START.date().isoformat()))
    end = str(raw.get("is_end", IS_END_LIMIT.date().isoformat()))
    _validate_window(start, end)
    symbols = list_symbols(exclude_boards=set(raw.get("exclude_boards", ["star", "b"])), at=None)
    max_symbols = int(raw["max_symbols"]) if raw.get("max_symbols") is not None else None
    symbols = sample_symbols(symbols, max_symbols, int(raw.get("sample_seed", 42)))
    prices = _load_prices(symbols, start, end)
    rows = []
    for spec in raw.get("factors", []):
        factor_name = str(spec["name"])
        params = dict(spec.get("params") or {})
        factor_frame = compute_factor_frame(factor_name, symbols, start, end, params=params)
        factor = _to_factor_series(factor_frame, factor_name).dropna()
        if factor.empty:
            rows.append(
                {
                    "factor": factor_name,
                    "params": params,
                    "ic_mean": np.nan,
                    "icir": np.nan,
                    "mean_n": 0.0,
                    "nonzero_mean": 0.0,
                    "quantile_spearman": np.nan,
                    "top_h5_avg": np.nan,
                    "top_h5_profit_factor": np.nan,
                    "decision": "invalid_or_uncertain",
                }
            )
            continue
        ic = rank_ic(factor, horizon=int(raw.get("horizon", 5)), prices=prices)
        qret = quantile_returns(factor, q=5, horizon=int(raw.get("horizon", 5)), prices=prices)
        top_result = _top_quantile_event(factor_frame, prices, horizon=int(raw.get("horizon", 5)))
        rows.append(
            {
                "factor": factor_name,
                "params": params,
                "ic_mean": float(ic.attrs["summary"]["mean"]),
                "icir": float(ic.attrs["summary"]["ir"]),
                "mean_n": float(ic.attrs["summary"]["mean_n"]),
                "nonzero_mean": float(ic["nonzero"].mean()) if not ic.empty else np.nan,
                "quantile_spearman": _quantile_spearman(qret),
                "top_h5_avg": top_result["avg_return"],
                "top_h5_profit_factor": top_result["profit_factor"],
                "decision": "",
            }
        )
    table = pd.DataFrame(rows)
    table["decision"] = np.where(
        table["icir"].abs().ge(0.3) & table["quantile_spearman"].abs().ge(0.8),
        "effective",
        "invalid_or_uncertain",
    )
    return _write_report(name, table, Path(str(raw.get("report_dir", "backtest_results/research"))))


def _to_factor_series(frame: pd.DataFrame, name: str) -> pd.Series:
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.rename(columns={"factor": name})
    return data.set_index(["date", "symbol"])[name].sort_index()


def _load_prices(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    qfq = get_ohlcv_batch(
        symbols,
        start=start,
        end=end,
        adjust="qfq",
        fields=("open", "close"),
    )
    raw = get_ohlcv_batch(
        symbols,
        start=start,
        end=end,
        adjust="raw",
        fields=("open", "suspended", "limit_up_price"),
    ).rename(columns={"open": "raw_open", "suspended": "is_suspended"})
    if qfq.empty:
        raise ValueError("no symbols to load")
    return qfq.merge(raw, on=["symbol", "date"], how="left")


def _top_quantile_event(
    factor_frame: pd.DataFrame, prices: pd.DataFrame, *, horizon: int
) -> dict[str, float]:
    frame = factor_frame.dropna(subset=["factor"]).copy()
    if frame.empty:
        return {"avg_return": np.nan, "profit_factor": np.nan}
    frame["date"] = pd.to_datetime(frame["date"])
    cut = frame.groupby("date")["factor"].transform(lambda x: x.quantile(0.8))
    signals = frame.assign(sig=frame["factor"] >= cut)[["symbol", "date", "sig"]]
    result = run_event_study(signals, horizons=[horizon], prices=prices, entry_filters="ashare")
    pooled = result.pooled
    if pooled.empty:
        return {"avg_return": np.nan, "profit_factor": np.nan}
    row = pooled.iloc[0]
    return {"avg_return": float(row["avg_return"]), "profit_factor": float(row["profit_factor"])}


def _quantile_spearman(qret: pd.DataFrame) -> float:
    if qret.empty:
        return np.nan
    mean_by_q = qret.groupby("quantile")["mean_return"].mean()
    if len(mean_by_q) < 5:
        return np.nan
    return float(
        pd.Series(mean_by_q.index, index=mean_by_q.index).corr(mean_by_q, method="spearman")
    )


def _write_report(name: str, table: pd.DataFrame, report_dir: Path) -> dict[str, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    csv_path = report_dir / f"{name}_exploratory.csv"
    md_path = report_dir / f"{name}_exploratory.md"
    table.to_csv(csv_path, index=False)
    lines = [
        f"# Exploratory Factor Research: {name}",
        "",
        "IS-only factor checks. Returns are before fees.",
        "",
        table.to_markdown(index=False),
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"csv": csv_path, "md": md_path}


def _validate_window(start: str, end: str) -> None:
    if pd.Timestamp(start) > pd.Timestamp(end):
        raise ValueError("is_start must be <= is_end")
    if pd.Timestamp(end) > IS_END_LIMIT:
        raise ValueError(f"is_end exceeds IS end {IS_END_LIMIT.date().isoformat()}")
