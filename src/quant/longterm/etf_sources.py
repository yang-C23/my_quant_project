"""Offline ETF evidence adapters; source prices and cash events remain separate."""

from __future__ import annotations

import json
from pathlib import Path
import re

import numpy as np
import pandas as pd


def local_dates(timestamps) -> pd.DatetimeIndex:
    """Provider epochs are converted to exchange dates, never UTC calendar dates."""
    return (
        pd.DatetimeIndex(pd.to_datetime(timestamps, unit="s", utc=True))
        .tz_convert("America/New_York")
        .tz_localize(None)
        .normalize()
    )


def chart_prices(path: Path, symbol: str, cutoff: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Undo Yahoo's split-only Close convention before applying real split events.

    AdjClose is deliberately not used: its dividend timing and underlying event
    corrections cannot replace a raw-price cash ledger. Quotes retain float64.
    """
    source = json.loads(path.read_text())["chart"]["result"][0]
    if source["meta"]["symbol"].upper() != symbol:
        raise ValueError("unexpected symbol in chart response")
    bars = pd.DataFrame(source["indicators"]["quote"][0], index=local_dates(source["timestamp"]))
    bars = bars.astype({column: "float64" for column in ("open", "high", "low", "close", "volume")})
    bars.index.name = "date"
    events = []
    for event in source.get("events", {}).get("splits", {}).values():
        date = local_dates([event["date"]])[0]
        ratio = event["numerator"] / event["denominator"]
        if not np.isfinite(ratio) or ratio <= 0:
            raise ValueError("invalid split")
        # Close/OHLC are expressed in post-split units. Historical volume is
        # restored to the same old-share units; used only for tradability here.
        before = bars.index < date
        bars.loc[before, ["open", "high", "low", "close"]] *= ratio
        bars.loc[before, "volume"] /= ratio
        events.append(
            dict(
                event_id=f"{symbol}:split:{date.date()}",
                symbol=symbol,
                kind="split",
                ex_date=date,
                pay_date=pd.NaT,
                per_share=np.nan,
                ratio=ratio,
                source="chart_split_event_requires_publisher_corroboration",
            )
        )
    bars = bars.loc[:cutoff].copy()
    if not bars.index.is_unique or not bars.index.is_monotonic_increasing:
        raise ValueError("duplicate or unordered quote dates")
    prices = bars[["open", "high", "low", "close"]]
    if not np.isfinite(prices).all().all() or (prices <= 0).any().any():
        raise ValueError("missing/invalid ETF prices; no forward filling")
    # Sub-cent fractions were valid before decimalisation; keep six decimals,
    # enough for historical 1/64 prices. The raw float bytes remain archived.
    bars.loc[:, prices.columns] = prices.round(6)
    if not np.isfinite(bars.volume).all() or (bars.volume < 0).any():
        raise ValueError("invalid volume")
    if not np.allclose(bars.volume, bars.volume.round(), atol=1e-6, rtol=0):
        raise ValueError("split-restored share volume is not integral")
    bars["volume"] = bars.volume.round().astype("int64")
    return bars, pd.DataFrame(events)


def ssga_actions(path: Path, symbol: str, cutoff: str, *, start: str | None = None) -> pd.DataFrame:
    """Use issuer per-old-share amounts, including capital-gain distributions."""
    frame = pd.read_excel(path, sheet_name="dividend")
    frame = frame[frame.TICKER.str.strip().eq(symbol)].copy()
    if frame.empty:
        raise ValueError("issuer workbook has no requested fund")
    dates = pd.to_datetime(frame["EX-DATE"])
    amounts = frame[
        ["DIVIDEND ($)", "SHORT TERM CAPITAL GAIN ($)", "LONG TERM CAPITAL GAIN ($)"]
    ].apply(pd.to_numeric, errors="raise")
    if amounts.isna().all(axis=1).any():
        raise ValueError("entire distribution amount missing")
    out = pd.DataFrame(
        {
            "event_id": [f"{symbol}:distribution:{d.date()}" for d in dates],
            "symbol": symbol,
            "kind": "dividend",
            "ex_date": dates,
            "pay_date": pd.to_datetime(frame["PAYABLE DATE"]),
            "per_share": amounts.fillna(0).sum(axis=1).round(6),
            "ratio": np.nan,
            "source": "SSGA_dividend_workbook",
        }
    )
    eligible = out.ex_date.le(cutoff)
    if start:
        eligible &= out.ex_date.ge(start)
    return validate_actions(out[eligible])


def nasdaq_actions(path: Path, symbol: str, start: str, cutoff: str) -> pd.DataFrame:
    """Only explicit provider pay dates; no invented old-date payment schedule."""
    source = json.loads(path.read_text())["data"]["dividends"]["rows"]
    out = pd.DataFrame(
        [
            dict(
                event_id=f"{symbol}:distribution:{pd.Timestamp(r['exOrEffDate']).date()}",
                symbol=symbol,
                kind="dividend",
                ex_date=pd.Timestamp(r["exOrEffDate"]),
                pay_date=pd.Timestamp(r["paymentDate"]),
                per_share=float(r["amount"].replace("$", "").replace(",", "")),
                ratio=np.nan,
                source="Nasdaq_dividend_table_not_fund_issuer",
            )
            for r in source
        ]
    )
    return validate_actions(out[out.ex_date.between(start, cutoff)])


def issuer_table_actions(path: Path, symbol: str, cutoff: str) -> pd.DataFrame:
    """Parse retained issuer table text; explicitly not original response bytes.

    This adapter is for independently archived search-rendered issuer evidence.
    It cannot establish the original historical publication time or a licence.
    """
    rows = re.findall(
        r"(\d{2}/\d{2}/\d{4})\s*\|\s*(\d{2}/\d{2}/\d{4})\s*\|\s*"
        r"(\d{2}/\d{2}/\d{4})\s*\|\s*([0-9.]+)",
        path.read_text(),
    )
    frame = pd.DataFrame(
        rows, columns=["ex_date", "record_date", "pay_date", "per_share"]
    ).drop_duplicates()
    if frame.empty:
        raise ValueError("no issuer cash events")
    for column in ("ex_date", "record_date", "pay_date"):
        frame[column] = pd.to_datetime(frame[column], format="%m/%d/%Y")
    frame["per_share"] = frame.per_share.astype(float)
    frame["event_id"] = [f"{symbol}:distribution:{date.date()}" for date in frame.ex_date]
    frame = frame.assign(
        symbol=symbol, kind="dividend", ratio=np.nan, source="issuer_table_via_search_archive"
    )
    return validate_actions(frame[frame.ex_date.le(cutoff)])


def combine_distribution_evidence(
    issuer: pd.DataFrame, exchange: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Explicit issuer precedence; every disagreement is emitted for review."""
    overlap = issuer.merge(exchange, on="ex_date", suffixes=("_issuer", "_exchange"))
    conflicts = overlap[
        (overlap.per_share_issuer != overlap.per_share_exchange)
        | (overlap.pay_date_issuer != overlap.pay_date_exchange)
    ].copy()
    missing = exchange[~exchange.ex_date.isin(issuer.ex_date)]
    return validate_actions(pd.concat([issuer, missing], ignore_index=True)), conflicts


def validate_actions(actions: pd.DataFrame) -> pd.DataFrame:
    """Reject duplicate entitlements and impossible availability dates."""
    if actions.event_id.duplicated().any():
        raise ValueError("duplicate corporate action")
    div = actions[actions.kind.eq("dividend")]
    if (
        div.pay_date.isna().any()
        or (div.pay_date < div.ex_date).any()
        or not np.isfinite(div.per_share).all()
        or (div.per_share < 0).any()
    ):
        raise ValueError("unverified cash distribution")
    return actions.sort_values(["ex_date", "kind"]).reset_index(drop=True)


def calendar_check(bars: pd.DataFrame, sessions: pd.DatetimeIndex) -> dict:
    """Return every gap; callers must explicitly refuse or adjudicate it."""
    expected = sessions[(sessions >= bars.index[0]) & (sessions <= bars.index[-1])]
    return {
        "missing": [str(d.date()) for d in expected.difference(bars.index)],
        "unexpected": [str(d.date()) for d in bars.index.difference(expected)],
    }


def causal_total_return(bars: pd.DataFrame, actions: pd.DataFrame) -> pd.DataFrame:
    """Ex-date gross total-return signal, forward chained without future scaling.

    This is a signal series, not a claim that receivable dividends are cash.
    Investment accounts use raw quotes and real payment dates instead.
    """
    ratio = pd.Series(1.0, index=bars.index)
    dividend = pd.Series(0.0, index=bars.index)
    for row in actions.itertuples():
        if row.ex_date not in bars.index:
            raise ValueError("company action lacks a market session")
        if row.kind == "split":
            ratio.loc[row.ex_date] *= row.ratio
        else:
            dividend.loc[row.ex_date] += row.per_share
    # Dividends on a split day would require explicit pre/post-unit conventions.
    if ((ratio != 1) & (dividend != 0)).any():
        raise ValueError("same-day split/dividend unit ordering requires adjudication")
    returns = (bars.close * ratio + dividend) / bars.close.shift(1)
    return pd.DataFrame({"close": returns.fillna(1.0).cumprod() * 100})
