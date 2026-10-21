"""Cboe's disseminated S&P price history, with explicit licensing/return limits."""

from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

from quant.data.catalog import DataCatalog
from quant.data.providers import observation_quality
from quant.data.snapshots import sha256_file, write_json

SPX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/SPX_History.csv"
PARSER_VERSION = "cboe-spx-close-v1"


def parse_spx(raw: bytes) -> pd.DataFrame:
    """Do not import zero placeholder opens/volume from the chart JSON."""
    frame = pd.read_csv(io.BytesIO(raw))
    if list(frame) != ["DATE", "SPX"]:
        raise ValueError("Cboe SPX schema changed")
    frame = frame.rename(columns={"DATE": "date", "SPX": "close"})
    frame["date"] = pd.to_datetime(frame.date, format="%m/%d/%Y", errors="raise")
    frame["close"] = pd.to_numeric(frame.close, errors="raise").astype("float64")
    if frame.date.duplicated().any() or not frame.date.is_monotonic_increasing:
        raise ValueError("SPX dates must be unique and increasing")
    if not np.isfinite(frame.close).all() or frame.close.le(0).any():
        raise ValueError("SPX prices must be positive finite observations")
    if frame.date.dt.dayofweek.ge(5).any():
        raise ValueError("unexpected weekend price")
    frame["symbol"] = "SP500"
    frame["available_at"] = (
        (frame.date + pd.Timedelta(hours=17))
        .dt.tz_localize("America/New_York")
        .dt.tz_convert("UTC")
    )
    return frame


def ingest_spx_probe(data_root: Path, probe: Path) -> dict:
    """Append a reproducible exploratory vintage; never enable production alerts."""
    raw = (probe / "cboe_spx_csv.raw").read_bytes()
    receipt = json.loads((probe / "cboe_spx_csv.receipt.json").read_text())
    if receipt["url"] != SPX_URL or receipt["status"] != 200:
        raise ValueError("unexpected source receipt")
    if receipt["sha256"] != sha256_file(probe / "cboe_spx_csv.raw"):
        raise ValueError("SPX source checksum mismatch")
    frame = parse_spx(raw)
    catalog = DataCatalog(data_root)
    # The FRED overlap is a diagnostic, not a correction or an independent
    # underlying index calculation. Both disseminate the same S&P licensor.
    old = catalog.read("fred_sp500", version="d209369708d3fffdfe3d5805")
    old["date"] = pd.to_datetime(old.date)
    matched = frame.merge(old[["date", "close"]], on="date", suffixes=("_cboe", "_fred"))
    matched["absolute_difference"] = (matched.close_cboe - matched.close_fred).abs()
    matched.to_csv(probe / "fred_overlap.csv", index=False)
    chart = json.loads((probe / "cboe_spx_json.raw").read_text())
    chart_frame = pd.DataFrame(chart["data"])
    chart_frame["date"] = pd.to_datetime(chart_frame.date)
    chart_frame["close"] = pd.to_numeric(chart_frame.close)
    chart_match = frame.merge(chart_frame[["date", "close"]], on="date", suffixes=("_csv", "_json"))
    if chart["symbol"] != "_SPX" or chart_frame.date.duplicated().any():
        raise ValueError("chart identity/date mismatch")
    quality = observation_quality(frame) | {
        "fred_overlap_rows": len(matched),
        "fred_dates_missing": int(len(old) - len(matched)),
        "fred_max_abs_difference": float(matched.absolute_difference.max()),
        "fred_different_rows": int(matched.absolute_difference.gt(1e-9).sum()),
        "chart_overlap_rows": len(chart_match),
        "chart_max_abs_difference": float(
            (chart_match.close_csv - chart_match.close_json).abs().max()
        ),
        "available_at_status": "assumed_observation_close_not_verified_publication_vintage",
        "formal_accepted": False,
        "long_term_storage_authorized": None,
        "license_review": "limited_personal_download_clause; archival_and_derived_use_unresolved",
    }
    source = receipt | {
        "publisher": "Cboe Global Indices; underlying S&P Dow Jones Indices",
        "landing_page": "https://www.cboe.com/us/indices/dashboard/spx/",
        "terms": "https://www.cboe.com/terms/",
        "redistribution": False,
        "persistent_storage": None,
        "terms_evidence_sha256": sha256_file(probe / "cboe_terms.raw"),
    }
    manifest = catalog.ingest(
        "cboe_spx_close",
        raw,
        frame,
        source=source,
        parser_version=PARSER_VERSION,
        quality=quality,
        metadata={"market": "US", "return_basis": "price_index_no_dividends"},
    )
    summary = {
        "dataset": manifest["dataset"],
        "version": manifest["version"],
        "rows": len(frame),
        "first": str(frame.date.min().date()),
        "last": str(frame.date.max().date()),
        "quality": quality,
        "production_gate": "blocked_license_and_publication_vintage",
    }
    write_json(probe / "ingest.json", summary)
    return summary
