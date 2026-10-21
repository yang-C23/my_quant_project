"""Conservative archive-time valuations, preserving each historical file version."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def parse_shiller_vintage(path: Path, available_at: str) -> pd.DataFrame:
    """Read P and E columns by their labels across old and new workbook formats."""
    book = pd.ExcelFile(path)
    frame = pd.read_excel(book, sheet_name="Data" if "Data" in book.sheet_names else 0, header=None)
    headers = frame[0].astype(str).str.strip().eq("Date")
    if headers.sum() != 1:
        raise ValueError("ambiguous Shiller date header")
    location = int(np.flatnonzero(headers)[0])
    header = frame.iloc[location].astype(str).str.strip().tolist()
    if header.count("P") != 1 or header.count("E") != 1:
        raise ValueError("P/E schema changed")
    data = frame.iloc[location + 1 :]
    raw = pd.to_numeric(data[0], errors="coerce")
    mask = raw.between(1871, 2100)
    encoded = raw.loc[mask].to_numpy()
    year = np.floor(encoded).astype(int)
    month = np.rint((encoded - year) * 100).astype(int)
    if ((month < 1) | (month > 12)).any():
        raise ValueError("invalid YYYY.MM source month")
    dates = pd.to_datetime({"year": year, "month": month, "day": 1}) + pd.offsets.MonthEnd(0)
    out = pd.DataFrame(
        {
            "date": dates.to_numpy(),
            "price": pd.to_numeric(data.loc[mask, header.index("P")], errors="coerce").to_numpy(),
            "earnings": pd.to_numeric(
                data.loc[mask, header.index("E")], errors="coerce"
            ).to_numpy(),
            "available_at": pd.Timestamp(available_at),
            "vintage": path.stem,
        }
    )
    if not out.date.is_unique:
        raise ValueError("duplicate month in vintage")
    # Future months in publisher sheets may be projections. Never use them.
    boundary = pd.Timestamp(available_at).tz_convert("America/New_York").tz_localize(None)
    out = out[out.date < boundary.normalize()]
    return out.sort_values("date").reset_index(drop=True)


def archive_temperature(
    close: pd.Series,
    vintages: pd.DataFrame,
    *,
    years: int = 10,
    maximum_age_days: int = 185,
    decision_times: pd.Series | None = None,
) -> pd.DataFrame:
    """Use the file known by today's close, never a later revision of its history."""
    if not close.index.is_unique or not close.index.is_monotonic_increasing:
        raise ValueError("unique ordered decision dates required")
    if years < 1 or maximum_age_days < 1:
        raise ValueError("positive history and freshness bounds required")
    if not np.isfinite(close).all() or (close <= 0).any():
        raise ValueError("positive finite decision prices required")
    if vintages.empty:
        raise ValueError("no archived observations")
    data = vintages.copy()
    data["available_at"] = pd.to_datetime(data.available_at, utc=True)
    if data[["vintage", "date"]].duplicated().any():
        raise ValueError("duplicate vintage/month")
    versions = []
    for name, part in data.groupby("vintage", sort=False):
        if part.available_at.nunique() != 1:
            raise ValueError("one file must have exactly one availability timestamp")
        versions.append((part.available_at.iloc[0], name, part.sort_values("date")))
    versions.sort(key=lambda row: (row[0], row[1]))
    if len({row[0] for row in versions}) != len(versions):
        raise ValueError("ambiguous equal-time archive versions")
    releases = pd.DatetimeIndex([row[0] for row in versions])
    if decision_times is None:
        decisions = (close.index + pd.Timedelta(hours=16)).tz_localize("America/New_York")
    else:
        known_closes = decision_times.reindex(close.index)
        if known_closes.isna().any():
            raise ValueError("exchange closing timestamp missing")
        decisions = pd.DatetimeIndex(pd.to_datetime(known_closes, utc=True))
    lookup = releases.searchsorted(decisions, side="right") - 1
    rows = []
    for date, price, pos in zip(close.index, close.to_numpy(), lookup):
        row = dict(temperature=np.nan, pe=np.nan, earnings=np.nan, vintage=None, history_count=0)
        if pos < 0:
            rows.append(row)
            continue
        release, name, part = versions[pos]
        known = part[(part.date < date) & np.isfinite(part.earnings)]
        row.update(vintage=name, available_at=release)
        if known.empty or (date - known.date.iloc[-1]).days > maximum_age_days:
            rows.append(row)
            continue
        latest = known.iloc[-1]
        if latest.earnings <= 0:
            rows.append(row)
            continue
        current = price / latest.earnings
        month_start = date.to_period("M").start_time
        history = known[
            (known.date >= month_start - pd.DateOffset(years=years)) & (known.date < month_start)
        ]
        values = history.price / history.earnings.where(history.earnings > 0)
        values = values[np.isfinite(values) & (values > 0)]
        row.update(pe=current, earnings=latest.earnings, history_count=len(values))
        if (
            known.date.iloc[0] <= date - pd.DateOffset(years=years)
            and len(values) >= 12 * years * 0.8
        ):
            row["temperature"] = float(
                ((values < current).sum() + 0.5 * (values == current).sum()) / len(values)
            )
        rows.append(row)
    return pd.DataFrame(rows, index=close.index)
