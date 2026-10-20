"""Free first-party pressure datasets with source-specific units and coverage checks."""

from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.parse import urlencode
import zipfile

import pandas as pd

from quant.data.catalog import DataCatalog
from quant.data.providers import download, observation_quality
from quant.data.snapshots import utc_now, write_json


def parse_sse_margin(documents: list[dict], observed_at: str) -> pd.DataFrame:
    """Shanghai balances are aggregate financing, not a forced-liquidation ledger."""
    rows = [row for document in documents for row in document["result"]]
    frame = pd.DataFrame(rows)
    mapping = {
        "opDate": "date",
        "rzye": "financing_balance_cny",
        "rzmre": "financing_purchases_cny",
        "rzche": "financing_repayments_cny",
        "rqyl": "borrowed_shares",
        "rqylje": "short_balance_cny",
        "rqmcl": "short_sales_shares",
        "rzrqjyzl": "total_margin_balance_cny",
    }
    if not set(mapping).issubset(frame):
        raise ValueError("SSE margin schema changed")
    frame = frame[list(mapping)].rename(columns=mapping)
    frame["date"] = pd.to_datetime(frame.date, format="%Y%m%d")
    frame["symbol"] = "SSE_MARGIN"
    frame["available_at"] = pd.Timestamp(observed_at)
    for column in set(frame) - {"date", "symbol", "available_at"}:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if (frame[column].dropna() < 0).any():
            raise ValueError("negative margin field requires adjudication")
    for column in ("borrowed_shares", "short_sales_shares"):
        frame[column] = frame[column].astype("Int64")
    if frame.date.duplicated().any():
        raise ValueError("duplicated SSE pages or dates")
    residual = (
        frame.total_margin_balance_cny - frame.financing_balance_cny - frame.short_balance_cny
    )
    if residual.isna().any() or residual.abs().max() > 1:
        raise ValueError("SSE financing plus securities lending does not reconcile")
    return frame.sort_values("date").reset_index(drop=True)


def fetch_sse_margin(data_root: Path, *, end: str, probe_dir: Path | None = None) -> dict:
    """Follow the actual 2,000-row server limit; never silently truncate at page one."""
    url = "https://query.sse.com.cn/marketdata/tradedata/queryMargin.do"
    pages, raw_pages, receipts = [], [], []
    total, page = None, 1
    while total is None or sum(len(x["result"]) for x in pages) < total:
        if page > 10:
            raise ValueError("SSE paging exceeds the bounded historical request")
        parameters = {
            "isPagination": "true",
            "beginDate": "20100331",
            "endDate": end.replace("-", ""),
            "tabType": "",
            "stockCode": "",
            "pageHelp.pageSize": "2000",
            "pageHelp.pageNo": str(page),
            "pageHelp.beginPage": str(page),
            "pageHelp.cacheSize": "1",
            "pageHelp.endPage": str(page),
        }
        raw, receipt = download(
            url + "?" + urlencode(parameters), headers={"Referer": "https://www.sse.com.cn/"}
        )
        if probe_dir:
            (probe_dir / f"sse_page_{page}.json").write_bytes(raw)
            write_json(
                probe_dir / f"sse_page_{page}_source.json", receipt | {"parameters": parameters}
            )
        document = json.loads(raw)
        if not document.get("result"):
            raise ValueError("empty SSE page before reported end")
        total = int(document["pageHelp"]["total"])
        pages.append(document)
        raw_pages.append(raw)
        receipts.append(receipt | {"parameters": parameters})
        page += 1
    observed = utc_now()
    frame = parse_sse_margin(pages, observed)
    if len(frame) != total or (frame.date > pd.Timestamp(end)).any():
        raise ValueError("SSE response coverage inconsistent with query")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for n, raw in enumerate(raw_pages):
            archive.writestr(zipfile.ZipInfo(f"page_{n + 1}.json", (1980, 1, 1, 0, 0, 0)), raw)
    return DataCatalog(data_root).ingest(
        "sse_margin_daily",
        stream.getvalue(),
        frame,
        source={
            "publisher": "Shanghai Stock Exchange",
            "pages": receipts,
            "redistribution": False,
            "persistent_storage": None,
        },
        parser_version="sse-margin-summary-v1",
        quality=observation_quality(frame),
        metadata={
            "market": "CN",
            "scope": "Shanghai_only_not_China_total_or_index_specific",
            "currency": "CNY",
            "money_unit": "yuan",
            "share_unit": "shares",
            "publication_timestamps": "first_observed_not_verified_historical_release",
            "repayments": "voluntary_forced_and_adjustments_not_identified_separately",
            "retention": "review_pending_not_sole_long_term_source",
            "requested_end": end,
            "server_total": total,
        },
    )


def parse_cboe_pressure(raw: bytes, name: str, observed_at: str) -> pd.DataFrame:
    """Separate index levels from put/call contract counts and old reporting regimes."""
    frame = pd.read_csv(io.BytesIO(raw), skiprows=2 if name == "total_putcall" else 0)
    frame.columns = frame.columns.str.strip()
    names = (
        {
            "DATE": "date",
            "CALLS": "calls",
            "PUTS": "puts",
            "TOTAL": "total",
            "P/C Ratio": "put_call_ratio",
        }
        if name == "total_putcall"
        else {"DATE": "date", "SKEW": "skew"}
        if name == "skew"
        else {"DATE": "date", "OPEN": "open", "HIGH": "high", "LOW": "low", "CLOSE": "close"}
    )
    if not set(names).issubset(frame):
        raise ValueError("Cboe pressure CSV schema changed")
    frame = frame[list(names)].rename(columns=names)
    frame["date"] = pd.to_datetime(frame.date, format="%m/%d/%Y")
    for column in set(frame) - {"date"}:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    if name == "total_putcall":
        for column in ("calls", "puts", "total"):
            frame[column] = frame[column].astype("Int64")
        if not (frame.calls + frame.puts).eq(frame.total).all():
            raise ValueError("put/call volumes do not sum to published total")
        if ((frame.puts / frame.calls) - frame.put_call_ratio).abs().max() > 0.00501:
            raise ValueError("reported put/call ratio rounding mismatch")
    if frame.date.duplicated().any():
        raise ValueError("duplicate Cboe observations")
    frame["symbol"] = name.upper()
    frame["available_at"] = pd.Timestamp(observed_at)
    return frame.sort_values("date").reset_index(drop=True)


def fetch_pressure_data(data_root: Path, *, end: str, cached_cboe_dir: Path | None = None) -> dict:
    """Record each unavailable source, preserving valid independent datasets."""
    catalog = DataCatalog(data_root)
    probe = (
        data_root
        / "source_probes"
        / pd.Timestamp.now(tz="UTC").strftime("pressure-%Y%m%dT%H%M%S%fZ")
    )
    probe.mkdir(parents=True)
    outputs = []
    jobs = {
        "vxn": "https://cdn.cboe.com/api/global/us_indices/daily_prices/VXN_History.csv",
        "skew": "https://cdn.cboe.com/api/global/us_indices/daily_prices/SKEW_History.csv",
        "total_putcall": "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/totalpc.csv",
    }
    for name, url in jobs.items():
        try:
            filename = "cboe_putcall.csv" if name == "total_putcall" else f"cboe_{name}.csv"
            if cached_cboe_dir:
                raw, source = (cached_cboe_dir / filename).read_bytes(), {"url": url}
            else:
                raw, source = download(url)
            (probe / filename).write_bytes(raw)
            write_json(probe / f"{filename}.source.json", source)
            frame = parse_cboe_pressure(raw, name, utc_now())
            source.update(publisher="Cboe", redistribution=False, persistent_storage=None)
            manifest = catalog.ingest(
                f"cboe_{name}",
                raw,
                frame,
                source=source,
                parser_version="cboe-pressure-v1",
                quality=observation_quality(frame),
                metadata={
                    "market": "US",
                    "basis": "published_index"
                    if name != "total_putcall"
                    else "Cboe_total_contract_volume_ratio",
                    "publication_timestamps": "first_observed_not_verified_historical_release",
                    "retention": "review_pending_not_sole_long_term_source",
                    "reporting_break": "2012-06-01_cleared_to_preliminary"
                    if name == "total_putcall"
                    else None,
                    "net_dealer_gamma": "not_observed",
                },
            )
            outputs.append(
                {
                    "status": "fetched",
                    "dataset": manifest["dataset"],
                    "version": manifest["version"],
                    "rows": len(frame),
                    "first_date": manifest["first_date"],
                    "last_date": manifest["last_date"],
                }
            )
        except Exception as exc:
            outputs.append(
                {"status": "unavailable", "dataset": f"cboe_{name}", "reason": repr(exc)}
            )
    try:
        manifest = fetch_sse_margin(data_root, end=end, probe_dir=probe)
        outputs.append(
            {
                "status": "fetched",
                "dataset": manifest["dataset"],
                "version": manifest["version"],
                "rows": manifest["rows"],
                "first_date": manifest["first_date"],
                "last_date": manifest["last_date"],
            }
        )
    except Exception as exc:
        outputs.append(
            {"status": "unavailable", "dataset": "sse_margin_daily", "reason": repr(exc)}
        )
    report = {"retrieved_at": utc_now(), "results": outputs}
    write_json(data_root / "source_reports/pressure.json", report)
    return report
