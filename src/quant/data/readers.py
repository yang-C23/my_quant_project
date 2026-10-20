"""Explicit immutable-snapshot queries; legacy history is not falsely labelled PIT."""

from __future__ import annotations

import json

import duckdb
import pandas as pd

from quant.config import Settings
from quant.data.snapshots import SnapshotStore


def daily_bars(
    settings: Settings,
    symbols: list[str],
    *,
    snapshot_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
    as_of: str | None = None,
    strict_pit: bool = True,
) -> pd.DataFrame:
    """Read a specified snapshot without changing the active-data pointer."""
    store = SnapshotStore(settings.data_root)
    selected = snapshot_id or store.current()
    if selected is None:
        raise ValueError("explicit data snapshot is required")
    if not store.verify(selected)["ok"]:
        raise ValueError("snapshot integrity verification failed")
    root = store.path(selected)
    manifest = json.loads((root / "manifest.json").read_text())
    if strict_pit and not manifest.get("pit_verified", False):
        raise ValueError("TDX historical publication/vintage evidence is unverified")
    conditions = ["symbol IN (SELECT unnest(?))"]
    parameters: list = [str(root / "staging/daily/**/*.parquet"), symbols]
    if start:
        conditions.append("date>=?::DATE")
        parameters.append(start)
    if end:
        conditions.append("date<=?::DATE")
        parameters.append(end)
    if as_of:
        cutoff = pd.Timestamp(as_of)
        if cutoff.tzinfo is None:
            raise ValueError("as_of requires timezone")
        if cutoff < pd.Timestamp(manifest["created_at"]):
            raise ValueError("snapshot was not observed by requested as_of time")
        conditions.append("date<=?::DATE")
        parameters.append(str(cutoff.tz_convert("Asia/Shanghai").date()))
    with duckdb.connect() as connection:
        frame = connection.execute(
            "SELECT * FROM read_parquet(?) WHERE "
            + " AND ".join(conditions)
            + " ORDER BY symbol,date",
            parameters,
        ).df()
    frame.attrs.update(
        snapshot_id=selected,
        research_grade=manifest.get("research_grade"),
        available_at=manifest["created_at"],
        pit_verified=manifest.get("pit_verified", False),
    )
    return frame
