#!/usr/bin/env python
"""Validate v2 staging/qlib data against frozen PostgreSQL v1 tables."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ValidationIssue:
    """One validation mismatch."""

    check: str
    symbol: str
    date: str
    column: str
    v2: float | str | int | None
    pg: float | str | int | None
    delta: float | None = None


@dataclass(frozen=True)
class CheckResult:
    """Validation result for one check."""

    check: str
    status: str
    total: int
    issues: tuple[ValidationIssue, ...] = ()


def _status(issues: list[ValidationIssue], *, warn: bool = False) -> str:
    if not issues:
        return "PASS"
    return "WARN" if warn else "FAIL"


def _keyed(left: pd.DataFrame, right: pd.DataFrame) -> pd.DataFrame:
    merged = left.merge(
        right,
        on=["symbol", "date"],
        how="outer",
        suffixes=("_v2", "_pg"),
        indicator=True,
    )
    merged["date"] = pd.to_datetime(merged["date"]).dt.date.astype(str)
    return merged


def compare_row_counts(v2_daily: pd.DataFrame, pg_daily: pd.DataFrame) -> CheckResult:
    """C3: compare row counts per symbol."""
    v2_counts = v2_daily.groupby("symbol").size()
    pg_counts = pg_daily.groupby("symbol").size()
    symbols = sorted(set(v2_counts.index) | set(pg_counts.index))
    issues = [
        ValidationIssue(
            "C3",
            symbol,
            "",
            "row_count",
            int(v2_counts.get(symbol, 0)),
            int(pg_counts.get(symbol, 0)),
        )
        for symbol in symbols
        if int(v2_counts.get(symbol, 0)) != int(pg_counts.get(symbol, 0))
    ]
    return CheckResult("C3 row counts", _status(issues), len(symbols), tuple(issues))


def compare_raw_ohlcv(
    v2_daily: pd.DataFrame,
    pg_daily: pd.DataFrame,
    *,
    columns: Iterable[str] = ("open", "high", "low", "close", "volume", "amount"),
    atol: float = 1e-9,
) -> CheckResult:
    """C4: compare raw OHLCV/amount values."""
    merged = _keyed(v2_daily, pg_daily)
    issues: list[ValidationIssue] = []
    missing = merged[merged["_merge"].ne("both")]
    for row in missing[["symbol", "date", "_merge"]].to_dict("records"):
        issues.append(
            ValidationIssue("C4", row["symbol"], row["date"], "_merge", str(row["_merge"]), "both")
        )
    both = merged[merged["_merge"].eq("both")]
    for col in columns:
        lv = pd.to_numeric(both[f"{col}_v2"], errors="coerce")
        rv = pd.to_numeric(both[f"{col}_pg"], errors="coerce")
        bad = (lv - rv).abs() > atol
        for row, delta in zip(both[bad].itertuples(index=False), (lv[bad] - rv[bad]), strict=True):
            issues.append(
                ValidationIssue(
                    "C4",
                    row.symbol,
                    row.date,
                    col,
                    getattr(row, f"{col}_v2"),
                    getattr(row, f"{col}_pg"),
                    float(delta),
                )
            )
    return CheckResult("C4 raw OHLCV", _status(issues), len(merged), tuple(issues))


def compare_hfq(
    v2_daily: pd.DataFrame,
    v2_adjust: pd.DataFrame,
    pg_daily: pd.DataFrame,
    pg_adjust: pd.DataFrame,
    *,
    pg_hfq_view: pd.DataFrame | None = None,
    rtol: float = 1e-6,
    view_abs_band: float = 0.005,
) -> tuple[CheckResult, CheckResult | None]:
    """C5: compare hfq factors and recomputed hfq prices.

    The hard check recomputes both sides as ``daily_kline.close * hfq_factor``.
    PG ``v_hfq_daily`` is rounded to 2 decimals, so it is only checked as an
    absolute warning band when supplied.
    """
    v2 = v2_daily[["symbol", "date", "close"]].merge(v2_adjust, on=["symbol", "date"])
    pg = pg_daily[["symbol", "date", "close"]].merge(pg_adjust, on=["symbol", "date"])
    merged = _keyed(v2, pg)
    issues: list[ValidationIssue] = []
    both = merged[merged["_merge"].eq("both")].copy()
    factor_bad = ~np.isclose(
        both["hfq_factor_v2"].astype(float),
        both["hfq_factor_pg"].astype(float),
        rtol=rtol,
        atol=0.0,
        equal_nan=True,
    )
    for row in both[factor_bad].itertuples(index=False):
        issues.append(
            ValidationIssue(
                "C5",
                row.symbol,
                row.date,
                "hfq_factor",
                row.hfq_factor_v2,
                row.hfq_factor_pg,
                float(row.hfq_factor_v2 - row.hfq_factor_pg),
            )
        )
    v2_hfq = both["close_v2"].astype(float) * both["hfq_factor_v2"].astype(float)
    pg_hfq = both["close_pg"].astype(float) * both["hfq_factor_pg"].astype(float)
    price_bad = ~np.isclose(v2_hfq, pg_hfq, rtol=rtol, atol=0.0, equal_nan=True)
    for row, left, right in zip(
        both[price_bad].itertuples(index=False), v2_hfq[price_bad], pg_hfq[price_bad], strict=True
    ):
        issues.append(
            ValidationIssue(
                "C5",
                row.symbol,
                row.date,
                "hfq_close_recalc",
                float(left),
                float(right),
                float(left - right),
            )
        )
    hard = CheckResult("C5 hfq recomputed", _status(issues), len(merged), tuple(issues))

    if pg_hfq_view is None:
        return hard, None
    view = v2.assign(hfq_close=v2["close"] * v2["hfq_factor"]).merge(
        pg_hfq_view[["symbol", "date", "close"]].rename(columns={"close": "view_close"}),
        on=["symbol", "date"],
        how="inner",
    )
    view_delta = (view["hfq_close"].astype(float) - view["view_close"].astype(float)).abs()
    view_issues = [
        ValidationIssue(
            "C5_VIEW",
            row.symbol,
            str(pd.Timestamp(row.date).date()),
            "view_abs_delta",
            row.hfq_close,
            row.view_close,
            float(delta),
        )
        for row, delta in zip(
            view[view_delta > view_abs_band].itertuples(index=False),
            view_delta[view_delta > view_abs_band],
            strict=True,
        )
    ]
    return hard, CheckResult(
        "C5 PG hfq view 0.005 band", _status(view_issues, warn=True), len(view), tuple(view_issues)
    )


def truncate_to_common_window(
    v2_daily: pd.DataFrame, pg_daily: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp]:
    """Truncate comparison inputs to min(pg_max_date, v2_max_date)."""
    v2 = v2_daily.copy()
    pg = pg_daily.copy()
    v2["date"] = pd.to_datetime(v2["date"])
    pg["date"] = pd.to_datetime(pg["date"])
    max_date = min(v2["date"].max(), pg["date"].max())
    return v2[v2["date"] <= max_date], pg[pg["date"] <= max_date], max_date


def write_markdown_report(results: Iterable[CheckResult], path: Path) -> None:
    """Write a markdown validation report."""
    rows = [
        {
            "check": result.check,
            "status": result.status,
            "total": result.total,
            "issues": len(result.issues),
        }
        for result in results
        if result is not None
    ]
    detail_rows = [
        issue.__dict__ for result in results if result is not None for issue in result.issues[:50]
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = pd.DataFrame(rows)
    details = pd.DataFrame(detail_rows)
    text = ["# M1 validate_vs_pg", "", "## Summary", summary.to_markdown(index=False)]
    if not details.empty:
        text.extend(["", "## Issue Details Top50", details.to_markdown(index=False)])
    path.write_text("\n".join(text), encoding="utf-8")


def main() -> int:
    """Run the PG validation report."""
    import psycopg2

    from quant.config import get_settings

    settings = get_settings()
    if not settings.pg_dsn:
        raise SystemExit("QUANT_DB_DSN is empty; start/configure pg_quant before validate")
    try:
        conn = psycopg2.connect(settings.pg_dsn)
    except psycopg2.OperationalError as exc:
        raise SystemExit(
            f"cannot connect to PG; did you run `docker start pg_quant`? {exc}"
        ) from exc

    try:
        pg_daily = pd.read_sql(
            "select symbol,date,open,high,low,close,volume,amount from tdx.daily_kline", conn
        )
        pg_adjust = pd.read_sql("select symbol,date,hfq_factor from tdx.adjust_factor", conn)
        pg_hfq = pd.read_sql("select symbol,date,close from tdx.v_hfq_daily", conn)
    finally:
        conn.close()

    v2_daily = pd.read_parquet(settings.staging_dir / "daily")
    v2_adjust = pd.read_parquet(settings.staging_dir / "adjust.parquet")
    # 统一 date dtype（parquet 为 date object，PG 为 datetime）：merge 键必须同型
    for frame in (pg_daily, pg_adjust, pg_hfq, v2_daily, v2_adjust):
        frame["date"] = pd.to_datetime(frame["date"])
    v2_daily, pg_daily, max_date = truncate_to_common_window(v2_daily, pg_daily)
    v2_adjust = v2_adjust[pd.to_datetime(v2_adjust["date"]) <= max_date]
    pg_adjust = pg_adjust[pd.to_datetime(pg_adjust["date"]) <= max_date]
    pg_hfq = pg_hfq[pd.to_datetime(pg_hfq["date"]) <= max_date]

    c3 = compare_row_counts(v2_daily, pg_daily)
    c4 = compare_raw_ohlcv(v2_daily, pg_daily)
    c5, c5_view = compare_hfq(v2_daily, v2_adjust, pg_daily, pg_adjust, pg_hfq_view=pg_hfq)
    write_markdown_report([c3, c4, c5, c5_view], Path("docs/reviews/M1-validate-vs-pg.md"))
    return 1 if any(result.status == "FAIL" for result in (c3, c4, c5)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
