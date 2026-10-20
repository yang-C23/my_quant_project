"""Issuer NAV and reviewed company actions; no inferred dividend payment dates."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from urllib.parse import urlencode
import zipfile

import numpy as np
import pandas as pd

from quant.data.catalog import DataCatalog
from quant.data.providers import download, observation_quality
from quant.data.snapshots import sha256_file, utc_now


def parse_huatai_nav(raw: bytes, symbol: str) -> pd.DataFrame:
    """Issuer unit/cumulative NAV are distinct from exchange execution prices."""
    document = json.loads(raw)
    if document.get("legend") != ["单位净值", "累计净值"]:
        raise ValueError("unrecognized issuer NAV semantics")
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(document["xAxisData"]),
            "unit_nav": pd.to_numeric(document["seriesData0"]),
            "cumulative_nav": pd.to_numeric(document["seriesData1"]),
            "symbol": symbol,
        }
    )
    return _validate_nav(frame)


def parse_igw_nav(raw: bytes, symbol: str) -> pd.DataFrame:
    """Read the issuer's downloadable daily NAV workbook, preserving the raw file."""
    frame = pd.read_excel(io.BytesIO(raw))
    names = {"净值日期": "date", "单位净值": "unit_nav", "累计净值（元）": "cumulative_nav"}
    if not set(names).issubset(frame):
        raise ValueError("IGW NAV workbook schema changed")
    frame = frame[list(names)].rename(columns=names)
    frame["date"] = pd.to_datetime(frame.date)
    frame["symbol"] = symbol
    return _validate_nav(frame)


def _validate_nav(frame: pd.DataFrame) -> pd.DataFrame:
    for column in ("unit_nav", "cumulative_nav"):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
        if not np.isfinite(frame[column]).all() or (frame[column] <= 0).any():
            raise ValueError("issuer NAV must be positive and finite")
    if frame.date.duplicated().any():
        raise ValueError("duplicate issuer NAV date")
    frame["available_at"] = pd.Timestamp(utc_now())
    return frame.sort_values("date").reset_index(drop=True)


def fetch_issuer_nav(
    data_root: Path, symbol: str, *, end: str, cached_file: Path | None = None
) -> dict:
    """Public issuer downloads, separately labelled pending retention/PIT acceptance."""
    if symbol in {"sh512890", "sh510300"}:
        publisher = "Huatai-PineBridge"
        url = "https://www.huatai-pb.com/common-web/chart/fundnetchart/getFundNetChartJson"
        parameters = {
            "fundcode": symbol[2:],
            "charttype": "2",
            "siteId": "9496d23c648f4a72a79150c3f2ac669b",
            "from": "2012-01-01" if symbol == "sh510300" else "2018-12-19",
            "to": end,
        }
        if cached_file is None:
            raw, source = download(
                url,
                data=urlencode(parameters).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        else:
            raw, source = cached_file.read_bytes(), {"url": url}
        source["public_query_parameters"] = parameters
        frame = parse_huatai_nav(raw, symbol)
    elif symbol == "sh515100":
        publisher = "Invesco Great Wall"
        url = "https://www.igwfmc.com/servlet/exportFundNav?" + urlencode(
            {
                "startDate": "2020-05-22",
                "endDate": end,
                "fundid": "515100",
                "curPage": 1,
                "pageSize": 99999,
            }
        )
        if cached_file is None:
            raw, source = download(url)
        else:
            raw, source = cached_file.read_bytes(), {"url": url}
        frame = parse_igw_nav(raw, symbol)
    else:
        raise ValueError("unsupported named fund case study")
    if (frame.date > pd.Timestamp(end)).any():
        raise ValueError("issuer returned dates outside the requested range")
    source.update(publisher=publisher, redistribution=False, persistent_storage=None)
    return DataCatalog(data_root).ingest(
        f"issuer_nav_{symbol}",
        raw,
        frame,
        source=source,
        parser_version="issuer-nav-v1",
        quality=observation_quality(frame),
        metadata={
            "market": "CN",
            "basis": "unit_nav_and_cumulative_nav_not_trade_quotes",
            "publication_timestamps": "first_observed",
            "retention": "review_pending_not_sole_long_term_source",
        },
    )


def reconcile_nav_actions(
    nav: pd.DataFrame, actions: pd.DataFrame, *, precision_periods: list[dict] | None = None
) -> dict:
    """Test the declared simple cumulative-NAV convention against every issuer date.

    This is a completeness cross-check in addition to original action notices.
    It is not permission to infer missing payment dates or silently repair a fund.
    """
    frame = nav.sort_values("date").copy()
    dates = pd.to_datetime(frame.date)
    ratio = pd.Series(1.0, index=frame.index)
    paid_per_original_unit = pd.Series(0.0, index=frame.index)
    running_ratio = 1.0
    for action in actions.sort_values("ex_date").to_dict("records"):
        after = dates >= pd.Timestamp(action["ex_date"])
        if action["kind"] == "split":
            running_ratio *= float(action["ratio"])
            ratio.loc[after] *= float(action["ratio"])
        elif action["kind"] == "dividend":
            if pd.isna(action.get("pay_date")):
                raise ValueError("a NAV jump cannot supply a missing payment date")
            paid_per_original_unit.loc[after] += float(action["per_share"]) * running_ratio
        else:
            raise ValueError("unsupported action type")
    expected = frame.unit_nav * ratio + paid_per_original_unit
    residual = frame.cumulative_nav - expected
    unit_quantum = pd.Series(0.0001, index=frame.index)
    cumulative_quantum = pd.Series(0.0001, index=frame.index)
    for period in precision_periods or []:
        if period["unit_decimals"] not in {3, 4} or period["cumulative_decimals"] not in {3, 4}:
            raise ValueError("unsupported NAV disclosure precision")
        affected = dates.between(period["start"], period["end"])
        unit_quantum.loc[affected] = 10.0 ** -period["unit_decimals"]
        cumulative_quantum.loc[affected] = 10.0 ** -period["cumulative_decimals"]
    tolerance = (unit_quantum * ratio + cumulative_quantum) / 2 + 1e-8
    return {
        "ok": bool((residual.abs() <= tolerance).all()),
        "rows": len(frame),
        "maximum_absolute_residual": float(residual.abs().max()),
        "maximum_rounding_tolerance": float(tolerance.max()),
        "precision_periods": precision_periods or [],
        "failed_dates": dates[residual.abs() > tolerance].dt.strftime("%Y-%m-%d").tolist(),
        "formula": "cumulative_nav = unit_nav * cumulative_split_ratio + distributions_per_original_unit",
    }


def reviewed_nav_corrections(nav: pd.DataFrame, declaration: dict) -> pd.DataFrame:
    """Apply exact, evidence-backed exceptions for reconciliation only; keep raw intact."""
    frame = nav.copy()
    evidence_hashes = {item["sha256"] for item in declaration["evidence"]}
    for correction in declaration.get("nav_corrections", []):
        if correction["evidence_sha256"] not in evidence_hashes:
            raise ValueError("NAV correction requires a pinned original disclosure")
        mask = pd.to_datetime(frame.date).eq(pd.Timestamp(correction["date"]))
        if mask.sum() != 1 or correction["field"] not in {"unit_nav", "cumulative_nav"}:
            raise ValueError("invalid NAV correction scope")
        field = correction["field"]
        if float(frame.loc[mask, field].iloc[0]) != correction["original"]:
            raise ValueError("NAV exception no longer matches original observation")
        if not correction.get("reason") or correction["verified_value"] <= 0:
            raise ValueError("explicit correction basis and positive NAV required")
        frame.loc[mask, field] = correction["verified_value"]
    return frame


def ingest_reviewed_actions(data_root: Path, declaration: dict) -> dict:
    """Import explicitly reviewed terms with exact source hashes and a bounded scope."""
    symbol = declaration["symbol"]
    actions = pd.DataFrame(declaration["actions"])
    if actions.empty or actions.event_id.duplicated().any():
        raise ValueError("nonempty unique action declarations required")
    actions["date"] = pd.to_datetime(actions.ex_date)
    actions["symbol"] = symbol
    actions["available_at"] = pd.Timestamp(utc_now())
    for column in ("ex_date", "record_date", "pay_date", "announcement_date"):
        if column in actions:
            actions[column] = pd.to_datetime(actions[column])
    if actions[["ex_date", "record_date", "announcement_date"]].isna().any().any():
        raise ValueError("reviewed action dates must be explicit")
    if (actions.announcement_date > actions.ex_date).any():
        raise ValueError("announcement date cannot follow the effective date")
    dividends = actions[actions.kind.eq("dividend")]
    if len(dividends) and (
        dividends.pay_date.isna().any() or (dividends.pay_date < dividends.ex_date).any()
    ):
        raise ValueError("cash distributions require valid verified payment dates")
    stream = io.BytesIO()
    proofs = []
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for number, proof in enumerate(declaration["evidence"]):
            path = data_root / proof["data_root_relative_path"]
            if not path.resolve().is_relative_to(data_root.resolve()):
                raise ValueError("evidence path leaves the data root")
            if sha256_file(path) != proof["sha256"]:
                raise ValueError("reviewed evidence changed")
            # Deterministic ZIP metadata, not today's timestamp.
            member = zipfile.ZipInfo(
                f"source_{number:03d}{path.suffix}", date_time=(1980, 1, 1, 0, 0, 0)
            )
            archive.writestr(member, path.read_bytes())
            proofs.append(
                {key: value for key, value in proof.items() if key != "data_root_relative_path"}
            )
        archive.writestr(
            zipfile.ZipInfo("reviewed_declaration.json", date_time=(1980, 1, 1, 0, 0, 0)),
            json.dumps(declaration, ensure_ascii=False, sort_keys=True).encode(),
        )
    catalog = DataCatalog(data_root)
    nav_manifest = catalog.manifest(f"issuer_nav_{symbol}")
    nav = catalog.read(f"issuer_nav_{symbol}", version=nav_manifest["version"])
    reconciliation = reconcile_nav_actions(
        reviewed_nav_corrections(nav, declaration),
        actions,
        precision_periods=declaration.get("nav_precision_periods"),
    )
    if not reconciliation["ok"]:
        raise ValueError(f"issuer NAV/action reconciliation failed: {reconciliation}")
    coverage_end = min(str(nav.date.max()), declaration["coverage_end"])
    raw = stream.getvalue()
    return catalog.ingest(
        f"issuer_actions_{symbol}",
        raw,
        actions,
        source={
            "publisher": declaration["publisher"],
            "evidence": proofs,
            "redistribution": False,
            "persistent_storage": None,
            "bundle_sha256": hashlib.sha256(raw).hexdigest(),
        },
        parser_version="reviewed-fund-actions-v1",
        quality={
            "structurally_valid": True,
            "corporate_action_terms_verified": True,
            "research_grade": "exploratory",
            "pit_verified": False,
            "retention_review": "required",
        },
        metadata={
            "market": "CN",
            "basis": "actual_dividends_and_splits",
            "coverage_start": declaration["coverage_start"],
            "coverage_end": coverage_end,
            "nav_version": nav_manifest["version"],
            "nav_reconciliation": reconciliation,
            "nav_corrections": declaration.get("nav_corrections", []),
            "complete_within_reviewed_scope": True,
            "historical_universe_selection_verified": False,
        },
    )
