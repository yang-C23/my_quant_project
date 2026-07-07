#!/usr/bin/env python
"""Generate the TASK-013 mini staging fixture."""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from quant.etl.adjust import compute_adjust
from quant.etl.basics import compute_basics
from quant.etl.staging import parse_day_bytes

FIXTURES = Path(__file__).resolve().parent
OUT = FIXTURES / "staging_mini"


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    raw = parse_day_bytes((FIXTURES / "tdx" / "lday" / "sh600000.day").read_bytes(), "sh600000")
    main = raw.head(6).copy()
    star = raw.head(4).copy()
    star["symbol"] = "sh688001"
    star[["open", "high", "low", "close"]] = star[["open", "high", "low", "close"]] + 1.0
    daily = pd.concat([main, star], ignore_index=True)
    daily["date"] = pd.to_datetime(daily["date"])
    (OUT / "daily").mkdir()
    daily.to_parquet(OUT / "daily" / "part-000.parquet", index=False)

    first = pd.Timestamp(daily["date"].min())
    event_date = pd.Timestamp(main["date"].iloc[2])
    gbbq = pd.DataFrame(
        [
            ("sh600000", first, 5, 0.0, 0.0, 100.0, 200.0),
            ("sh688001", first, 5, 0.0, 0.0, 50.0, 80.0),
            ("sh600000", event_date, 1, 1.0, 0.0, 0.0, 0.0),
        ],
        columns=["symbol", "date", "category", "c1", "c2", "c3", "c4"],
    )
    gbbq.to_parquet(OUT / "gbbq.parquet", index=False)
    compute_basics(daily, gbbq).to_parquet(OUT / "basics.parquet", index=False)
    compute_adjust(daily, gbbq).to_parquet(OUT / "adjust.parquet", index=False)

    securities = pd.DataFrame(
        [
            ("sh600000", "600000", None, "sh", "stock", "main", main["date"].min(), pd.NaT),
            (
                "sh688001",
                "688001",
                None,
                "sh",
                "stock",
                "star",
                star["date"].min(),
                star["date"].max(),
            ),
        ],
        columns=[
            "symbol",
            "code",
            "name",
            "exchange",
            "sec_type",
            "board",
            "list_date",
            "delist_date",
        ],
    )
    securities.to_parquet(OUT / "securities.parquet", index=False)

    flags = daily[["symbol", "date"]].copy()
    flags["is_suspended"] = False
    flags["is_st"] = False
    flags["limit_up_price"] = pd.NA
    flags["limit_down_price"] = pd.NA
    flags["is_limit_up"] = False
    flags["is_limit_down"] = False
    flags.to_parquet(OUT / "flags.parquet", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
