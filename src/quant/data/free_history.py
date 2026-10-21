"""Free first-party history: preserve releases separately from observation dates."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from html import unescape
import io
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlparse

import pandas as pd

from quant.data.catalog import DataCatalog
from quant.data.derivatives import parse_cffex, parse_cftc
from quant.data.providers import download, observation_quality
from quant.data.snapshots import sha256_file, utc_now, write_json

VERSION = "first-party-history-v2-padded-contracts"
FINRA_URL = "https://www.finra.org/sites/default/files/2021-03/margin-statistics.xlsx"
SHILLER_URL = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"
SHILLER_MAINTAINED_PAGE = "https://shillerdata.com/"


def shiller_workbook_url(page: bytes) -> str:
    """Resolve the author's current download without guessing opaque CDN identifiers."""
    links = {
        urljoin(SHILLER_MAINTAINED_PAGE, unescape(link))
        for link in re.findall(r'href=["\']([^"\']+)["\']', page.decode("utf-8"))
        if "ie_data.xls" in link
    }
    if len(links) != 1:
        raise ValueError("ambiguous maintained Shiller workbook link")
    link = links.pop()
    parsed = urlparse(link)
    if parsed.scheme != "https" or parsed.hostname not in {"img1.wsimg.com", "shillerdata.com"}:
        raise ValueError("review changed Shiller download host before ingestion")
    return link


def ingest_maintained_shiller(data_root: Path, *, cached_dir: Path | None = None) -> dict:
    """Append the maintained author vintage; retain the stale Yale vintage for replay."""
    if cached_dir is None:
        cached_dir = (
            data_root
            / "source_probes"
            / ("shiller-maintained-" + pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%S%fZ"))
        )
        cached_dir.mkdir(parents=True)
        page, page_receipt = download(SHILLER_MAINTAINED_PAGE)
        (cached_dir / "index.html").write_bytes(page)
        write_json(
            cached_dir / "index.receipt.json",
            page_receipt
            | {"retrieved_at": utc_now(), "sha256": sha256_file(cached_dir / "index.html")},
        )
        raw, receipt = download(shiller_workbook_url(page))
        (cached_dir / "ie_data.xls").write_bytes(raw)
        write_json(
            cached_dir / "workbook.receipt.json",
            receipt
            | {"retrieved_at": utc_now(), "sha256": sha256_file(cached_dir / "ie_data.xls")},
        )
    page = (cached_dir / "index.html").read_bytes()
    source = json.loads((cached_dir / "workbook.receipt.json").read_text())
    page_receipt = json.loads((cached_dir / "index.receipt.json").read_text())
    if page_receipt["url"] != SHILLER_MAINTAINED_PAGE or (
        source["url"] != shiller_workbook_url(page)
        or source["sha256"] != sha256_file(cached_dir / "ie_data.xls")
        or page_receipt["sha256"] != sha256_file(cached_dir / "index.html")
    ):
        raise ValueError("maintained workbook provenance/hash mismatch")
    raw = (cached_dir / "ie_data.xls").read_bytes()
    frame = parse_shiller(raw, source["retrieved_at"])
    source.update(
        publisher="Robert J. Shiller maintained author website",
        landing_page=SHILLER_MAINTAINED_PAGE,
        landing_page_sha256=page_receipt["sha256"],
        attribution_corroboration="https://cowles.yale.edu/sites/default/files/2024-07/d2397.pdf",
        public_download=True,
        persistent_storage="permission_review_pending",
        redistribution=False,
    )
    return DataCatalog(data_root).ingest(
        "shiller_monthly",
        raw,
        frame,
        source=source,
        parser_version="maintained-author-workbook-v1",
        quality=observation_quality(frame),
        metadata={
            "market": "US",
            "historical_publication_verified": False,
            "availability": "first_observed_not_historical_release",
            "basis": "latest_vintage",
            "earnings_interpolation": True,
            "not_tradable_monthly_average_price": True,
            "incomplete_recent_earnings_not_forward_filled": True,
        },
    )


def parse_finra(raw: bytes, retrieved_at: str) -> pd.DataFrame:
    """Amounts are millions of USD; actual historical release instants are unknown."""
    frame = pd.read_excel(io.BytesIO(raw), sheet_name="Customer Margin Balances")
    names = {
        "Year-Month": "date",
        "Debit Balances in Customers' Securities Margin Accounts": "margin_debt_usd_million",
        "Free Credit Balances in Customers' Cash Accounts": "cash_credit_usd_million",
        "Free Credit Balances in Customers' Securities Margin Accounts": "margin_credit_usd_million",
    }
    if set(frame) != set(names):
        raise ValueError("FINRA workbook schema changed")
    frame = frame.rename(columns=names)
    dates = pd.to_datetime(frame["date"], format="%Y-%m", errors="coerce")
    if dates.isna().any():
        raise ValueError("unrecognized FINRA month")
    frame["date"] = dates + pd.offsets.MonthEnd(0)
    for name in set(names.values()) - {"date"}:
        frame[name] = pd.to_numeric(frame[name], errors="raise").astype("float64")
        if (frame[name].dropna() < 0).any():
            raise ValueError("negative FINRA balances")
    frame["symbol"] = "US_MARGIN_AGGREGATE"
    frame["available_at"] = pd.Timestamp(retrieved_at)
    return frame.sort_values("date").reset_index(drop=True)


def parse_shiller(raw: bytes, retrieved_at: str) -> pd.DataFrame:
    """Latest monthly vintage, interpolated earnings; explicitly not historical PIT."""
    original = pd.read_excel(io.BytesIO(raw), sheet_name="Data", header=7)
    required = {"Date", "P", "D", "E", "CPI", "Rate GS10", "CAPE"}
    if not required.issubset(original):
        raise ValueError(f"Shiller workbook schema changed: {list(original)}")
    original = original[pd.to_numeric(original["Date"], errors="coerce").notna()].copy()
    number = pd.to_numeric(original["Date"])
    year = number.astype(int)
    month = ((number - year) * 100).round().astype(int)
    if not month.between(1, 12).all():
        raise ValueError("invalid decimal YYYY.MM dates")
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(dict(year=year, month=month, day=1)) + pd.offsets.MonthEnd(0),
            "symbol": "US_SHILLER_COMPOSITE",
        }
    )
    for source, target in {
        "P": "monthly_average_price",
        "D": "interpolated_dividends_12m",
        "E": "interpolated_earnings_12m",
        "CPI": "cpi_latest_vintage",
        "Rate GS10": "bond_yield",
        "CAPE": "cape_latest_vintage",
    }.items():
        frame[target] = pd.to_numeric(original[source], errors="coerce")
    frame["bond_yield"] /= 100
    frame["pe_latest_vintage"] = (
        frame.monthly_average_price
        / frame.interpolated_earnings_12m.where(frame.interpolated_earnings_12m > 0)
    )
    frame["dividend_yield_latest_vintage"] = (
        frame.interpolated_dividends_12m / frame.monthly_average_price
    )
    frame["available_at"] = pd.Timestamp(retrieved_at)
    # Incomplete current month is not a completed historical observation.
    return frame[frame.date <= pd.Timestamp(retrieved_at).tz_localize(None)].reset_index(drop=True)


def ingest_official_workbook(
    data_root: Path, name: str, *, cached_file: Path | None = None
) -> dict:
    """A frozen downloaded workbook can be re-parsed without touching the network."""
    definitions = {
        "finra_margin": (FINRA_URL, parse_finra, "FINRA"),
        "shiller_monthly": (SHILLER_URL, parse_shiller, "Robert J. Shiller / Yale"),
    }
    url, parser, publisher = definitions[name]
    if cached_file is None:
        raw, source = download(url)
    else:
        raw, source = cached_file.read_bytes(), {"url": url, "cached_file": str(cached_file)}
    frame = parser(raw, utc_now())
    source.update(
        publisher=publisher,
        public_download=True,
        persistent_storage="permission_review_pending",
        redistribution=False,
    )
    return DataCatalog(data_root).ingest(
        name,
        raw,
        frame,
        source=source,
        parser_version=VERSION,
        quality=observation_quality(frame),
        metadata={
            "market": "US",
            "historical_publication_verified": False,
            "availability": "first_observed_not_historical_release",
            "basis": "latest_vintage",
            "known_breaks": ["2010_scope", "2021_reporting"] if name == "finra_margin" else [],
            "earnings_interpolation": name == "shiller_monthly",
            "not_tradable_monthly_average_price": name == "shiller_monthly",
        },
    )


def acquire_archives(
    data_root: Path,
    *,
    cftc_years: list[int],
    cffex_months: list[str] | None = None,
    workers: int = 2,
) -> dict:
    """Bounded, resumable archive retrieval; failures are retained, not substituted."""
    if not 1 <= workers <= 4:
        raise ValueError("use one to four archive workers")
    catalog = DataCatalog(data_root)
    jobs = []
    if cftc_years and min(cftc_years) < 2010:
        jobs.append(
            (
                "cftc_tff_futures_2006_2016",
                "https://www.cftc.gov/files/dea/history/fin_fut_txt_2006_2016.zip",
                parse_cftc,
                "CFTC",
            )
        )
    for year in cftc_years:
        if not 2006 <= year <= pd.Timestamp.now(tz="UTC").year:
            raise ValueError("unsupported CFTC year")
        if year < 2010 or (min(cftc_years) < 2010 and year <= 2016):
            continue
        jobs.append(
            (
                f"cftc_tff_futures_{year}",
                f"https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip",
                parse_cftc,
                "CFTC",
            )
        )
    for month in cffex_months or []:
        date = pd.to_datetime(month, format="%Y%m", errors="raise")
        if date < pd.Timestamp("2010-04-01") or date > pd.Timestamp.now().normalize():
            raise ValueError("invalid CFFEX month")
        jobs.append(
            (
                f"cffex_{month}",
                f"http://www.cffex.com.cn/sj/historysj/{month}/zip/{month}.zip",
                parse_cffex,
                "CFFEX",
            )
        )
    existing = {m["dataset"]: m for m in catalog.list_datasets()}
    directory = (
        data_root
        / "audits"
        / ("archive-acquisition-" + pd.Timestamp.now(tz="UTC").strftime("%Y%m%dT%H%M%S%fZ"))
    )
    directory.mkdir(parents=True)

    def one(job: tuple) -> dict:
        name, url, parser, publisher = job
        try:
            if name in existing and existing[name]["parser_version"] == VERSION:
                manifest = existing[name]
                catalog.verify_manifest(manifest)
                status = "existing_verified"
            else:
                if name in existing:
                    previous = existing[name]
                    catalog.verify_manifest(previous)
                    raw = (catalog.dataset_dir(name) / previous["version"] / "raw.bin").read_bytes()
                    source = previous["source"]
                else:
                    raw, source = download(url)
                # Preserve a parser failure for inspection and replay instead of
                # discarding the very source bytes which caused the failure.
                (directory / f"{name}.raw").write_bytes(raw)
                write_json(directory / f"{name}.source.json", source)
                frame = parser(raw, utc_now())
                quality = observation_quality(frame)
                if not quality["structurally_valid"]:
                    raise ValueError("archive failed structural checks")
                source.update(publisher=publisher, redistribution=False)
                manifest = catalog.ingest(
                    name,
                    raw,
                    frame,
                    source=source,
                    parser_version=VERSION,
                    quality=quality,
                    metadata={
                        "market": "US" if publisher == "CFTC" else "CN",
                        "availability": "first_observed_not_historical_release",
                        "volume_unit": "contracts",
                        "position_direction_not_dealer_gamma": True,
                    },
                )
                status = "fetched"
            record = {
                "dataset": name,
                "url": url,
                "status": status,
                **{key: manifest[key] for key in ("version", "rows", "first_date", "last_date")},
            }
        except Exception as exc:
            record = {"dataset": name, "url": url, "status": "failed", "reason": repr(exc)}
        write_json(directory / f"{name}.json", record)
        return record

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, jobs))
    summary = {"directory": str(directory), "results": results, "finished_at": utc_now()}
    write_json(directory / "summary.json", summary)
    return summary
