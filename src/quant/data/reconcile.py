"""Cross-source comparisons with explicit tolerances and coverage gaps."""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from quant.config import Settings
from quant.data.catalog import DataCatalog
from quant.data.snapshots import SnapshotStore, utc_now, write_json


def crosscheck(settings: Settings) -> dict:
    """Compare every overlapping observed index bar and the captured ETF sessions."""
    catalog = DataCatalog(settings.data_root)
    rows, differences, gaps = [], [], []
    snapshot_id = SnapshotStore(settings.data_root).current()
    if not snapshot_id:
        raise ValueError("a published snapshot is required")
    payload = SnapshotStore(settings.data_root).path(snapshot_id) / "staging/daily/**/*.parquet"
    for manifest in catalog.list_datasets():
        dataset = manifest["dataset"]
        if not dataset.startswith("baostock_"):
            continue
        frame = catalog.read(dataset, version=manifest["version"])
        frame["date"] = pd.to_datetime(frame["date"])
        conditions = "symbol IN (SELECT UNNEST(?))"
        parameters = [str(payload), frame.symbol.unique().tolist()]
        etf_session = dataset.startswith("baostock_etf_")
        if etf_session:
            conditions += " AND date>=?::DATE AND date<=?::DATE"
            parameters += [str(frame.date.min().date()), str(frame.date.max().date())]
        with duckdb.connect() as connection:
            local_frame = connection.execute(
                "SELECT * FROM read_parquet(?) WHERE " + conditions, parameters
            ).df()
        local_groups = {
            symbol: group.set_index("date").sort_index()
            for symbol, group in local_frame.groupby("symbol")
        }
        for symbol, source in frame.groupby("symbol"):
            if symbol not in local_groups:
                rows.append({"symbol": symbol, "dataset": dataset, "status": "local_missing"})
                continue
            local = local_groups[symbol]
            source = source.assign(date=pd.to_datetime(source.date)).set_index("date")
            common = source.index.intersection(local.index)
            if not len(common):
                rows.append({"symbol": symbol, "dataset": dataset, "status": "no_common_dates"})
                continue
            for label, dates in (
                ("local_only", local.index.difference(source.index)),
                ("source_only", source.index.difference(local.index)),
            ):
                gaps.extend(
                    {"symbol": symbol, "dataset": dataset, "date": str(date.date()), "side": label}
                    for date in dates
                )
            result = {
                "symbol": symbol,
                "dataset": dataset,
                "version": manifest["version"],
                "overlap": len(common),
                "local_only_dates": len(local.index.difference(source.index)),
                "source_only_dates": len(source.index.difference(local.index)),
            }
            for column in ("open", "high", "low", "close", "volume", "amount"):
                left = local.loc[common, column].astype(float)
                right = source.loc[common, column].astype(float)
                difference = (left - right).abs()
                relative = difference / right.abs().replace(0, np.nan)
                atol, rtol = (
                    ((0.00051 if etf_session else 0.0051), 1e-8)
                    if column in {"open", "high", "low", "close"}
                    else (1.0, 2e-6)
                )
                bad = ~np.isclose(left, right, atol=atol, rtol=rtol, equal_nan=False)
                differences.extend(
                    {
                        "symbol": symbol,
                        "dataset": dataset,
                        "date": str(date.date()),
                        "field": column,
                        "local_value": None if pd.isna(left.loc[date]) else float(left.loc[date]),
                        "source_value": None
                        if pd.isna(right.loc[date])
                        else float(right.loc[date]),
                    }
                    for date in common[bad]
                )
                result[f"{column}_mismatches"] = int(bad.sum())
                result[f"{column}_max_abs_difference"] = float(difference.max())
                result[f"{column}_max_relative_difference"] = (
                    float(relative.max()) if relative.notna().any() else None
                )
            result["status"] = (
                "within_tolerance"
                if all(
                    result[f"{c}_mismatches"] == 0
                    for c in ("open", "high", "low", "close", "volume", "amount")
                )
                else "differences_require_review"
            )
            rows.append(result)
    report = {
        "created_at": utc_now(),
        "snapshot_id": snapshot_id,
        "price_tolerance": {
            "ETF_absolute": 0.00051,
            "index_stock_absolute": 0.0051,
            "relative": 1e-8,
        },
        "activity_tolerance": {"absolute": 1.0, "relative": 2e-6},
        "results": rows,
        "limitations": [
            "matching two providers does not prove exchange-source correctness",
            "TDX activity encoding loses precision; do not claim exact units counts",
            "single-session ETF agreement does not certify all historical bars",
        ],
    }
    directory = settings.data_root / "source_reports"
    directory.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(differences).to_parquet(
        directory / "crosscheck_differences.parquet", index=False, compression="zstd"
    )
    pd.DataFrame(gaps).to_parquet(
        directory / "crosscheck_coverage_gaps.parquet", index=False, compression="zstd"
    )
    report["difference_records"] = len(differences)
    report["coverage_gap_records"] = len(gaps)
    write_json(directory / "crosscheck.json", report)
    return report
