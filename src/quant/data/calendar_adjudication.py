"""Explicit session corrections; missing quotes never become fabricated prices."""

from pathlib import Path
import json

import pandas as pd

from quant.data.snapshots import sha256_file


def adjudicate_sessions(bars: pd.DataFrame, asset: str, decision: dict, data_root: Path):
    """Require a fixed calendar and per-date evidence before changing a source."""
    path = data_root / decision["calendar_file"]
    if sha256_file(path) != decision["calendar_sha256"]:
        raise ValueError("calendar evidence checksum changed")
    expected = pd.DatetimeIndex(json.loads(path.read_text())["sessions"])
    expected = expected[(expected >= bars.index.min()) & (expected <= bars.index.max())]
    removed = pd.DatetimeIndex(decision["removed_non_sessions"][asset])
    if set(bars.index.difference(expected)) != set(removed):
        raise ValueError("unexpected non-session; explicit adjudication required")
    result = bars.drop(index=removed).copy()
    for date, close in decision["inserted_closes"].get(asset, {}).items():
        timestamp = pd.Timestamp(date)
        if timestamp in result.index or timestamp not in expected or close <= 0:
            raise ValueError("only a verified, missing session may be inserted")
        result.loc[timestamp, "close"] = float(close)
    result = result.sort_index()
    missing = expected.difference(result.index)
    if set(missing) != set(pd.DatetimeIndex(decision["unresolved_missing_sessions"][asset])):
        raise ValueError("unexpected calendar gap requires investigation")
    return result, {
        "removed_non_sessions": [str(d.date()) for d in removed],
        "inserted_closes": decision["inserted_closes"].get(asset, {}),
        "unresolved_missing_sessions": [str(d.date()) for d in missing],
        "calendar_version": decision["calendar_library"],
        "calendar_sha256": decision["calendar_sha256"],
    }
