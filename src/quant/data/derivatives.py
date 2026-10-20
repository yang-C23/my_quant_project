"""Official derivative/position archives with contract identity and honest release times."""

from __future__ import annotations

import io
from pathlib import Path
import re
import zipfile

import pandas as pd

from quant.data.catalog import DataCatalog
from quant.data.providers import PARSER_VERSION, download, observation_quality
from quant.data.snapshots import utc_now, write_json


def parse_cffex(raw: bytes, retrieved_at: str) -> pd.DataFrame:
    """Keep individual futures/options, excluding summary rows and retaining missing quotes."""
    parts = []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(item.file_size for item in archive.infolist()) > 128 * 1024 * 1024:
            raise ValueError("CFFEX archive expands beyond the 128 MiB limit")
        for member in archive.infolist():
            match = re.fullmatch(r"(\d{8})_\d+\.csv", Path(member.filename).name)
            if not match:
                continue
            frame = pd.read_csv(io.BytesIO(archive.read(member)), encoding="gb18030")
            mapping = {
                "合约代码": "symbol",
                "今开盘": "open",
                "最高价": "high",
                "最低价": "low",
                "今收盘": "close",
                "今结算": "settlement",
                "前结算": "previous_settlement",
                "成交量": "volume",
                "持仓量": "open_interest",
                "持仓变化": "open_interest_change",
                "成交金额": "turnover_source_value",
                "Delta": "delta",
            }
            if not {"合约代码", "成交量", "持仓量", "今结算"}.issubset(frame):
                raise ValueError("CFFEX contract schema changed")
            frame = frame.rename(columns=mapping)
            frame = frame[
                frame.symbol.astype(str).str.match(r"^[A-Z]+\d{4}(?:-[CP]-\d+(?:\.\d+)?)?$")
            ].copy()
            frame["date"] = pd.Timestamp(match[1])
            frame["available_at"] = pd.Timestamp(retrieved_at)
            for column in frame:
                if column not in {"symbol", "date", "available_at"}:
                    frame[column] = pd.to_numeric(frame[column], errors="coerce")
            for column in ("volume", "open_interest", "open_interest_change"):
                if column in frame:
                    frame[column] = frame[column].astype("Int64")
            parts.append(frame)
    if not parts:
        raise ValueError("no CFFEX daily contract files")
    return pd.concat(parts, ignore_index=True).sort_values(["symbol", "date"])


def parse_cftc(raw: bytes, retrieved_at: str) -> pd.DataFrame:
    """Tuesday position dates are NOT Friday publication dates; first-observed is explicit."""
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if sum(item.file_size for item in archive.infolist()) > 128 * 1024 * 1024:
            raise ValueError("CFTC archive expands beyond the 128 MiB limit")
        members = [n for n in archive.namelist() if n.lower().endswith(".txt")]
        if len(members) != 1:
            raise ValueError("unexpected CFTC archive structure")
        original = pd.read_csv(
            io.BytesIO(archive.read(members[0])), dtype={"CFTC_Contract_Market_Code": str}
        )
    names = {
        "Report_Date_as_YYYY-MM-DD": "date",
        "CFTC_Contract_Market_Code": "symbol",
        "Market_and_Exchange_Names": "market_name",
        "Open_Interest_All": "open_interest",
        "Dealer_Positions_Long_All": "dealer_long",
        "Dealer_Positions_Short_All": "dealer_short",
        "Asset_Mgr_Positions_Long_All": "asset_manager_long",
        "Asset_Mgr_Positions_Short_All": "asset_manager_short",
        "Lev_Money_Positions_Long_All": "leveraged_funds_long",
        "Lev_Money_Positions_Short_All": "leveraged_funds_short",
    }
    if not set(names).issubset(original):
        raise ValueError("CFTC TFF schema changed")
    frame = original[list(names)].rename(columns=names)
    frame["date"] = pd.to_datetime(frame["date"])
    frame["available_at"] = pd.Timestamp(retrieved_at)
    for column in set(frame) - {"date", "symbol", "market_name", "available_at"}:
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("Int64")
    return frame.sort_values(["symbol", "date"]).reset_index(drop=True)


def fetch_derivatives(data_root: Path, *, month: str, year: int) -> dict:
    """Capture one explicit CFFEX month and CFTC year without extrapolating coverage."""
    if not re.fullmatch(r"\d{6}", month) or not 2006 <= year <= 2100:
        raise ValueError("use YYYYMM month and a valid TFF year")
    pd.Timestamp(f"{month[:4]}-{month[4:]}-01")
    catalog = DataCatalog(data_root)
    jobs = [
        (
            f"cffex_{month}",
            f"http://www.cffex.com.cn/sj/historysj/{month}/zip/{month}.zip",
            parse_cffex,
            "CFFEX",
        ),
        (
            f"cftc_tff_futures_{year}",
            f"https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip",
            parse_cftc,
            "CFTC",
        ),
    ]
    results = []
    for name, url, parse, publisher in jobs:
        try:
            raw, source = download(url)
            frame = parse(raw, utc_now())
            quality = observation_quality(frame)
            if not quality["structurally_valid"]:
                raise ValueError("duplicate/nonfinite contract observations")
            source.update(publisher=publisher, redistribution=False)
            manifest = catalog.ingest(
                name,
                raw,
                frame,
                source=source,
                parser_version=PARSER_VERSION,
                quality=quality,
                metadata={
                    "market": "CN" if publisher == "CFFEX" else "US",
                    "availability": "first_observed_not_historical_release",
                    "volume_unit": "contracts",
                    "net_dealer_gamma": "not_observed",
                    "turnover_source_value_unit": "requires_official_definition_review",
                },
            )
            results.append(
                {
                    "dataset": name,
                    "status": "fetched",
                    "version": manifest["version"],
                    "rows": manifest["rows"],
                    "first_date": manifest["first_date"],
                    "last_date": manifest["last_date"],
                }
            )
        except Exception as exc:
            results.append(
                {"dataset": name, "status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}
            )
    report = {"created_at": utc_now(), "results": results}
    write_json(data_root / "source_reports/derivatives.json", report)
    return report
