"""Small, provenance-preserving public-source adapters; no paid subscriptions."""

from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import logging
import os
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from quant.data.catalog import DataCatalog
from quant.data.snapshots import utc_now, write_json

logger = logging.getLogger(__name__)
PARSER_VERSION = "public-daily-v2-typed-bounded"
CSI_CODES = ("000300", "000905", "000016", "000688", "000698", "000852", "H30269", "930955")


def download(url: str, *, headers: dict | None = None) -> tuple[bytes, dict]:
    """Fetch bounded public payloads, preserving origin without persisting credentials."""
    request = Request(
        url, headers={"User-Agent": "QuantResearch/1.0 personal research", **(headers or {})}
    )
    for attempt in range(3):
        try:
            with urlopen(request, timeout=20) as response:
                body = response.read(64 * 1024 * 1024 + 1)
                if len(body) > 64 * 1024 * 1024:
                    raise ValueError("response exceeds 64 MiB; use a partitioned download")
                return body, {
                    "url": url,
                    "resolved_url": response.url,
                    "content_type": response.headers.get("Content-Type"),
                    "last_modified": response.headers.get("Last-Modified"),
                }
        except HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(attempt + 1)
    raise RuntimeError("download retry exhausted")


def parse_fred(raw: bytes, series: str) -> pd.DataFrame:
    """Normalize a close-only price/macro series without inventing OHLC or dividends."""
    frame = pd.read_csv(io.BytesIO(raw))
    required = {"observation_date", series}
    if not required.issubset(frame):
        raise ValueError(f"FRED schema changed: expected {sorted(required)}")
    frame = frame.rename(columns={"observation_date": "date", series: "close"})
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["close"]).copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["symbol"] = series
    # Conservative observation-time assumption, not a verified historical vintage.
    frame["available_at"] = (
        (frame["date"] + pd.Timedelta(hours=17))
        .dt.tz_localize("America/New_York")
        .dt.tz_convert("UTC")
    )
    return frame.sort_values("date").reset_index(drop=True)


def parse_cboe_vix(raw: bytes) -> pd.DataFrame:
    """Read Cboe's official VIX history; spot VIX is not an investable asset."""
    frame = pd.read_csv(io.BytesIO(raw))
    if not {"DATE", "OPEN", "HIGH", "LOW", "CLOSE"}.issubset(frame):
        raise ValueError("Cboe VIX schema changed")
    frame = frame.rename(columns=str.lower)
    frame["date"] = pd.to_datetime(frame["date"], format="%m/%d/%Y")
    frame["symbol"] = "VIX"
    frame["available_at"] = (
        (frame["date"] + pd.Timedelta(hours=17))
        .dt.tz_localize("America/New_York")
        .dt.tz_convert("UTC")
    )
    for name in ("open", "high", "low", "close"):
        frame[name] = pd.to_numeric(frame[name], errors="raise").astype(float)
    return frame.sort_values("date").reset_index(drop=True)


def parse_csi_valuation(raw: bytes, symbol: str, retrieved_at: str) -> pd.DataFrame:
    """Keep total-share and index-share PE/yield separate; never backdate availability."""
    frame = pd.read_excel(io.BytesIO(raw))
    expected = [
        "日期Date",
        "市盈率1（总股本）P/E1",
        "市盈率2（计算用股本）P/E2",
        "股息率1（总股本）D/P1",
        "股息率2（计算用股本）D/P2",
    ]
    if not set(expected).issubset(frame):
        raise ValueError(f"CSI valuation schema changed: {frame.columns.tolist()}")
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(frame[expected[0]].astype(str), format="%Y%m%d"),
            "symbol": symbol,
            "pe_total": pd.to_numeric(frame[expected[1]], errors="coerce"),
            "pe_index_shares": pd.to_numeric(frame[expected[2]], errors="coerce"),
            "dividend_yield_total": pd.to_numeric(frame[expected[3]], errors="coerce") / 100,
            "dividend_yield_index_shares": pd.to_numeric(frame[expected[4]], errors="coerce") / 100,
            "available_at": pd.Timestamp(retrieved_at),
        }
    )
    return out.sort_values("date").reset_index(drop=True)


def observation_quality(frame: pd.DataFrame) -> dict:
    """Reject duplicate keys and nonfinite observed values, preserving missing fields."""
    keys = ["symbol", "date"]
    duplicates = int(frame.duplicated(keys).sum())
    numbers = frame.select_dtypes(include="number").to_numpy(dtype=float)
    infinite = int(np.isinf(numbers).sum())
    return {
        "structurally_valid": duplicates == 0 and infinite == 0 and len(frame) > 0,
        "duplicate_keys": duplicates,
        "infinite_values": infinite,
        "pit_verified": False,
        "research_grade": "exploratory",
        "retention_review": "required_before_sole_long_term_dependency",
    }


def fetch_reference_series(catalog: DataCatalog, series: str) -> dict:
    """Fetch FRED price/macro references with series-specific return semantics."""
    allowed = {"SP500", "NASDAQ100", "DGS10", "DTB3", "DEXCHUS"}
    if series not in allowed:
        raise ValueError("unsupported FRED reference")
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
    raw, source = download(url)
    frame = parse_fred(raw, series)
    source.update(
        publisher="FRED / original series licensor",
        terms="https://fred.stlouisfed.org/legal/",
        redistribution=False,
    )
    quality = observation_quality(frame)
    if not quality["structurally_valid"]:
        raise ValueError("reference series failed validation")
    return catalog.ingest(
        f"fred_{series.lower()}",
        raw,
        frame,
        source=source,
        parser_version=PARSER_VERSION,
        quality=quality,
        metadata={
            "market": "US",
            "price_basis": (
                "price_only_close"
                if series in {"SP500", "NASDAQ100"}
                else "yield_percent"
                if series in {"DGS10", "DTB3"}
                else "CNY_per_USD"
            ),
            "availability": "estimated_17h_New_York_not_vintage",
        },
    )


def fetch_vix(catalog: DataCatalog) -> dict:
    """Fetch official VIX observations."""
    raw, source = download(
        "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
    )
    frame = parse_cboe_vix(raw)
    source.update(
        publisher="Cboe",
        terms="https://www.cboe.com/legal/terms-and-conditions/",
        redistribution=False,
    )
    return catalog.ingest(
        "cboe_vix",
        raw,
        frame,
        source=source,
        parser_version=PARSER_VERSION,
        quality=observation_quality(frame),
        metadata={"market": "US", "tradable": False, "pre_2003": "backcalculated"},
    )


def fetch_csi(catalog: DataCatalog, symbol: str) -> dict:
    """Capture a recent official CSI valuation file for prospective accumulation."""
    if symbol not in CSI_CODES:
        raise ValueError("index is outside the approved CSI universe")
    url = (
        "https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/"
        f"autofile/indicator/{symbol}indicator.xls"
    )
    raw, source = download(url)
    frame = parse_csi_valuation(raw, symbol, utc_now())
    source.update(
        publisher="China Securities Index",
        redistribution=False,
        terms="https://www.csindex.com.cn/",
    )
    return catalog.ingest(
        f"csi_valuation_{symbol.lower()}",
        raw,
        frame,
        source=source,
        parser_version=PARSER_VERSION,
        quality=observation_quality(frame),
        metadata={
            "market": "CN",
            "availability": "first_observed",
            "history": "recent_file_not_long_term_PE_history",
        },
    )


def fetch_tiingo(
    catalog: DataCatalog, symbol: str, *, token: str, retention_agreement: str = ""
) -> dict:
    """Fetch EOD raw/adjusted ETF data only when an existing token is configured."""
    if not token:
        raise ValueError("TIINGO_API_TOKEN not configured; no paid service was purchased")
    if not retention_agreement:
        raise PermissionError(
            "Tiingo 2026-10-06 terms do not permit this permanent archive; "
            "a separately verified written retention agreement is required"
        )
    if symbol not in {"SPY", "IVV", "VOO", "QQQ", "QQQM", "SPHD"}:
        raise ValueError("symbol outside approved ETF candidates")
    url = f"https://api.tiingo.com/tiingo/daily/{symbol}/prices?startDate=1990-01-01"
    raw, source = download(url, headers={"Authorization": f"Token {token}"})
    frame = pd.DataFrame(json.loads(raw))
    if not {
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "adjClose",
        "divCash",
        "splitFactor",
    }.issubset(frame):
        raise ValueError("Tiingo EOD schema incomplete")
    frame["date"] = pd.to_datetime(frame["date"], utc=True).dt.tz_localize(None)
    frame["symbol"] = symbol
    frame["currency"] = "USD"
    frame["available_at"] = (
        (frame["date"] + pd.Timedelta(hours=21))
        .dt.tz_localize("America/New_York")
        .dt.tz_convert("UTC")
    )
    source.update(
        publisher="Tiingo",
        terms="https://app.tiingo.com/tos/",
        retention_agreement=retention_agreement,
        redistribution=False,
    )
    return catalog.ingest(
        f"tiingo_{symbol.lower()}",
        raw,
        frame,
        source=source,
        parser_version=PARSER_VERSION,
        quality=observation_quality(frame),
        metadata={
            "market": "US",
            "price_basis": "raw_and_vendor_adjusted",
            "dividend_pay_date": "not_provided",
        },
    )


def _fetch_baostock_unbounded(catalog: DataCatalog, symbols: list[str], *, end: str) -> list[dict]:
    """Probe full raw history per symbol; preserve unsupported products as failures."""
    import baostock as bs

    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"BaoStock login failed: {login.error_msg}")
    output = []
    try:
        for symbol in symbols:
            code = f"{symbol[:2]}.{symbol[2:]}"
            query = bs.query_history_k_data_plus(
                code,
                "date,code,open,high,low,close,volume,amount",
                start_date="1990-01-01",
                end_date=end,
                frequency="d",
                adjustflag="3",
            )
            if query.error_code != "0":
                output.append({"symbol": symbol, "status": "failed", "reason": query.error_msg})
                continue
            records = []
            while query.next():
                records.append(query.get_row_data())
            if query.error_code != "0":
                raise RuntimeError(f"incomplete BaoStock pagination: {query.error_msg}")
            frame = pd.DataFrame(records, columns=query.fields)
            if frame.empty:
                output.append(
                    {"symbol": symbol, "status": "unavailable", "reason": "empty history"}
                )
                continue
            raw = frame.to_csv(index=False).encode()
            frame = frame.rename(columns={"code": "symbol"})
            frame["symbol"] = symbol
            frame["date"] = pd.to_datetime(frame["date"])
            for name in ("open", "high", "low", "close", "volume", "amount"):
                frame[name] = pd.to_numeric(frame[name], errors="coerce")
            frame["volume"] = frame["volume"].astype("Int64")
            frame["available_at"] = (
                (frame["date"] + pd.Timedelta(hours=20))
                .dt.tz_localize("Asia/Shanghai")
                .dt.tz_convert("UTC")
            )
            source = {
                "publisher": "BaoStock",
                "url": "https://www.baostock.com/",
                "transport": "baostock_0.9.4",
                "adjustflag": "3",
                "raw_format": "lossless_API_string_table_CSV",
                "redistribution": False,
            }
            manifest = catalog.ingest(
                f"baostock_{symbol}",
                raw,
                frame,
                source=source,
                parser_version=PARSER_VERSION,
                quality=observation_quality(frame),
                metadata={"market": "CN", "price_basis": "unadjusted"},
            )
            output.append({"symbol": symbol, "status": "fetched", "manifest": manifest})
            logger.info("BaoStock %s: %s rows", symbol, len(frame))
    finally:
        bs.logout()
    return output


def fetch_public(data_root: Path, *, include_baostock: bool = False) -> dict:
    """Fetch free approved references; report every gap without synthetic substitution."""
    catalog = DataCatalog(data_root)
    jobs = [("cboe_vix", lambda: fetch_vix(catalog))]
    jobs += [
        (f"fred_{s.lower()}", lambda s=s: fetch_reference_series(catalog, s))
        for s in ("SP500", "NASDAQ100", "DGS10", "DTB3", "DEXCHUS")
    ]
    jobs += [(f"csi_valuation_{s.lower()}", lambda s=s: fetch_csi(catalog, s)) for s in CSI_CODES]
    token = os.environ.get("TIINGO_API_TOKEN", "")
    jobs += [
        (f"tiingo_{s.lower()}", lambda s=s: fetch_tiingo(catalog, s, token=token))
        for s in ("SPY", "QQQ", "SPHD")
    ]
    results = []
    for name, operation in jobs:
        try:
            manifest = operation()
            results.append(
                {
                    "dataset": name,
                    "status": "fetched",
                    "version": manifest["version"],
                    "rows": manifest["rows"],
                    "start": manifest["first_date"],
                    "end": manifest["last_date"],
                }
            )
        except Exception as exc:  # one external failure must not hide other source evidence
            results.append(
                {"dataset": name, "status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}
            )
        logger.info("%s: %s", name, results[-1]["status"])
    if include_baostock:
        try:
            results.extend(
                fetch_baostock(
                    catalog,
                    ["sh000300", "sh000905", "sh000016", "sh000852", "sz399006", "sh600000"],
                    end=datetime.now(timezone.utc).date().isoformat(),
                )
            )
        except Exception as exc:
            results.append(
                {
                    "dataset": "baostock",
                    "status": "unavailable",
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
    report = {
        "created_at": utc_now(),
        "results": results,
        "note": "fetched is not formal research acceptance; see each quality/retention gate",
    }
    write_json(data_root / "source_reports" / "latest.json", report)
    write_json(
        data_root / "source_reports" / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.json", report
    )
    return report


def _fetch_baostock_etf_day_unbounded(catalog: DataCatalog, date: str) -> dict:
    """Use the ETF-specific bulk daily API; the stock-history endpoint is unsuitable."""
    import baostock as bs

    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(login.error_msg)
    try:
        query = bs.query_daily_history_k_ETF(date=date)
        if query.error_code != "0":
            raise RuntimeError(query.error_msg)
        records = []
        while query.next():
            records.append(query.get_row_data())
        if query.error_code != "0":
            raise RuntimeError(query.error_msg)
        original = pd.DataFrame(records, columns=query.fields)
        if original.empty:
            raise ValueError("no ETF observations for this session")
        raw = original.to_csv(index=False).encode()
        frame = original[
            ["date", "code", "open", "high", "low", "close", "volume", "amount"]
        ].copy()
        frame = frame.rename(columns={"code": "symbol"})
        frame["symbol"] = frame["symbol"].str.replace(".", "", regex=False)
        frame["date"] = pd.to_datetime(frame["date"])
        for column in ("open", "high", "low", "close", "amount"):
            frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
        frame["volume"] = pd.to_numeric(frame["volume"], errors="raise").astype("Int64")
        frame["available_at"] = pd.Timestamp(utc_now())
        return catalog.ingest(
            f"baostock_etf_{date.replace('-', '')}",
            raw,
            frame,
            source={
                "publisher": "BaoStock",
                "url": "https://www.baostock.com/",
                "endpoint": "query_daily_history_k_ETF",
                "redistribution": False,
            },
            parser_version=PARSER_VERSION,
            quality=observation_quality(frame),
            metadata={
                "market": "CN",
                "price_basis": "raw",
                "volume_unit": "fund_units",
                "availability": "first_observed",
                "history": "single_session",
            },
        )
    finally:
        bs.logout()


def _bounded_baostock(catalog: DataCatalog, operation: str, **parameters) -> object:
    """Isolate the vendor socket client so a stuck query cannot stop a daily run."""
    import subprocess
    import sys
    import tempfile

    job = {"root": str(catalog.root.parent), "operation": operation, **parameters}
    with tempfile.TemporaryDirectory(prefix="quant-baostock-") as temporary:
        result = Path(temporary) / "result.json"
        job["result"] = str(result)
        worker = (
            "import json,sys; from pathlib import Path; "
            "from quant.data.providers import _baostock_worker; "
            "_baostock_worker(json.loads(sys.argv[1]))"
        )
        try:
            completed = subprocess.run(
                [sys.executable, "-c", worker, json.dumps(job)],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("BaoStock query exceeded 90 seconds; worker terminated") from exc
        if completed.returncode:
            raise RuntimeError(f"BaoStock worker failed: {completed.stderr[-2000:]}")
        return json.loads(result.read_text())


def _baostock_worker(job: dict) -> None:
    """Private process entry; normalized evidence is committed before returning."""
    catalog = DataCatalog(Path(job["root"]))
    if job["operation"] == "etf_day":
        result = _fetch_baostock_etf_day_unbounded(catalog, job["date"])
    elif job["operation"] == "history":
        result = _fetch_baostock_unbounded(catalog, job["symbols"], end=job["end"])
    else:
        raise ValueError("unsupported BaoStock operation")
    write_json(Path(job["result"]), result)


def fetch_baostock(catalog: DataCatalog, symbols: list[str], *, end: str) -> list[dict]:
    """Bound each symbol independently; one unsupported instrument cannot hang the rest."""
    results = []
    for symbol in symbols:
        try:
            results.extend(_bounded_baostock(catalog, "history", symbols=[symbol], end=end))
        except (TimeoutError, RuntimeError) as exc:
            results.append({"symbol": symbol, "status": "unavailable", "reason": str(exc)})
    return results


def fetch_baostock_etf_day(catalog: DataCatalog, date: str) -> dict:
    """Fetch the dedicated ETF session with a hard vendor-client timeout."""
    pd.Timestamp(date)
    return _bounded_baostock(catalog, "etf_day", date=date)
