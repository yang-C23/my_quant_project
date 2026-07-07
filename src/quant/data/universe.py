"""Point-in-time universe helpers based on staging metadata."""

from __future__ import annotations

import pandas as pd

from quant.config import get_settings


def _read_staging_table(name: str) -> pd.DataFrame:
    staging_dir = get_settings().staging_dir
    directory = staging_dir / name
    if directory.exists():
        return pd.read_parquet(directory)
    file_path = staging_dir / f"{name}.parquet"
    if file_path.exists():
        return pd.read_parquet(file_path)
    raise FileNotFoundError(f"missing staging table: {directory} or {file_path}")


def _filter_at(securities: pd.DataFrame, at: str | None) -> pd.DataFrame:
    if at is None:
        return securities
    asof = pd.Timestamp(at)
    listed = securities["list_date"] <= asof
    not_delisted = securities["delist_date"].isna() | (securities["delist_date"] >= asof)
    return securities[listed & not_delisted]


def _latest_float_mktcap(at: str | None) -> pd.Series:
    basics = _read_staging_table("basics")[["symbol", "date", "float_mktcap"]].copy()
    basics["date"] = pd.to_datetime(basics["date"])
    if at is not None:
        basics = basics[basics["date"] <= pd.Timestamp(at)]
    if basics.empty:
        return pd.Series(dtype=float)
    latest = basics.sort_values(["symbol", "date"]).groupby("symbol", sort=False).tail(1)
    return latest.set_index("symbol")["float_mktcap"].astype(float)


def list_symbols(
    *,
    sec_type: str = "stock",
    exclude_boards: set[str] = frozenset({"star"}),
    min_float_mktcap: float | None = None,
    at: str | None = None,
) -> list[str]:
    """Return a point-in-time symbol universe from staging securities.

    ``at`` filters by list/delist interval and therefore includes delisted
    names when they were live on the requested date.
    """
    securities = _read_staging_table("securities").copy()
    securities["list_date"] = pd.to_datetime(securities["list_date"])
    securities["delist_date"] = pd.to_datetime(securities["delist_date"])

    frame = securities[securities["sec_type"].eq(sec_type)].copy()
    if exclude_boards:
        frame = frame[~frame["board"].isin(exclude_boards)]
    frame = _filter_at(frame, at)

    if min_float_mktcap is not None:
        cap = _latest_float_mktcap(at)
        frame = frame[frame["symbol"].map(cap).ge(float(min_float_mktcap)).fillna(False)]

    return frame.sort_values("symbol")["symbol"].astype(str).tolist()
