"""Reconcile dated issuer disclosures with NAV, without turning narratives into signals."""

from __future__ import annotations

import json
from pathlib import Path
import re

import pandas as pd
from pypdf import PdfReader

from quant.data.catalog import DataCatalog
from quant.data.snapshots import sha256_file, write_json
from quant.etl.restart import code_revision
from quant.longterm.asset_inputs import prepare_action_prices


def disclosure_nav_index(nav: pd.Series, actions: pd.DataFrame) -> pd.Series:
    """CSRC disclosure convention; not the ETF cash-payment portfolio return.

    For a distribution D the reference is previous NAV minus D, rather than
    assuming reinvestment at today's closing NAV. Splits change the share basis.
    Reference: CSRC reporting rule 1, article 8. Keep this separate from economic
    total-return marks and the actual receivable/payment-date ledger.
    """
    reference = nav.shift(1)
    for action in actions.to_dict("records"):
        date = pd.Timestamp(action["ex_date"])
        if date not in nav.index:
            raise ValueError("disclosure action needs its NAV observation")
        if action["kind"] == "split":
            reference.loc[date] /= float(action["ratio"])
        elif action["kind"] == "dividend":
            reference.loc[date] -= float(action["per_share"])
        else:
            raise ValueError("unsupported disclosure action")
    if (reference.dropna() <= 0).any():
        raise ValueError("nonpositive disclosure reference NAV")
    growth = nav / reference
    growth.iloc[0] = 1
    return growth.cumprod()


def review_issuer_reports(
    data_root: Path, source: Path, documents: Path, destination: Path
) -> dict:
    """All 2021–2025 reports are reviewed; no selection by performance.

    Year-end industry weights are descriptive observations, not known throughout
    the preceding year. Daily tracking error is preserved at its stated frequency.
    The fixed document set is an audit of existing source evidence, not a strategy.
    """
    if destination.exists():
        raise ValueError("preserve old reviews; use a new directory")
    registration = json.loads((source / "registration.json").read_text())
    versions = registration["catalog_versions"]
    catalog = DataCatalog(data_root)
    rows, evidence = [], []
    funds = {"sh512890": "huatai512890", "sh515100": "igw515100"}
    for symbol, prefix in funds.items():
        nav = catalog.read(f"issuer_nav_{symbol}", version=versions[f"issuer_nav_{symbol}"])
        nav["date"] = pd.to_datetime(nav.date)
        bars = nav.set_index("date")[["unit_nav"]].rename(columns={"unit_nav": "close"})
        actions = catalog.read(
            f"issuer_actions_{symbol}", version=versions[f"issuer_actions_{symbol}"]
        )
        _, total, _ = prepare_action_prices(bars, actions)
        disclosure = disclosure_nav_index(bars.close, actions)
        for year in range(2021, 2026):
            path = documents / f"{prefix}_{year}.pdf"
            receipt = json.loads(path.with_suffix(".pdf.receipt.json").read_text())
            checksum = sha256_file(path)
            expected_hash = receipt.get("sha256")
            if expected_hash is None:
                expected_hash = json.loads(path.with_suffix(".pdf.sha256.json").read_text())[
                    "sha256"
                ]
            if checksum != expected_hash:
                raise ValueError("issuer report hash mismatch")
            text = "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
            performance = re.search(r"过去一年\s+" + r"([-+\d.]+)%\s*" * 6, text)
            financial = re.search(r"J\s+金融业\s+[\d,]+\.\d+\s+([\d.]+)", text)
            tracking = re.search(r"期间日跟踪误差为\s*([\d.]+)%", text)
            if not all((performance, financial)):
                raise ValueError(f"disclosure layout requires review: {symbol}/{year}")
            first = total.loc[: f"{year - 1}-12-31"].iloc[-1].close
            last = total.loc[: f"{year}-12-31"].iloc[-1].close
            computed = last / first - 1
            published_basis = (
                disclosure.loc[: f"{year}-12-31"].iloc[-1]
                / disclosure.loc[: f"{year - 1}-12-31"].iloc[-1]
                - 1
            )
            values = [float(x) / 100 for x in performance.groups()]
            rows.append(
                {
                    "symbol": symbol,
                    "year": year,
                    "reported_fund_return": values[0],
                    "ex_date_economic_total_return": computed,
                    "disclosure_basis_nav_return": published_basis,
                    "absolute_return_difference": abs(published_basis - values[0]),
                    "nav_reconciled_with_rounding": abs(published_basis - values[0]) <= 0.0003,
                    "reported_benchmark_return": values[2],
                    "fund_minus_reported_benchmark": values[4],
                    "year_end_index_stock_financial_weight": float(financial[1]) / 100,
                    "reported_daily_tracking_error": float(tracking[1]) / 100 if tracking else None,
                    "source_url": receipt["url"],
                    "sha256": checksum,
                }
            )
            evidence.append(
                {
                    "symbol": symbol,
                    "year": year,
                    "source": str(path),
                    "sha256": checksum,
                    "performance_excerpt": performance[0],
                    "industry_excerpt": financial[0],
                    "tracking_excerpt": tracking[0] if tracking else "not_numerically_reported",
                    "timing": "year_end_disclosure_not_a_contemporaneous_year_round_signal",
                }
            )
    destination.mkdir(parents=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(destination / "issuer_years.csv", index=False)
    write_json(destination / "evidence.json", evidence)
    write_json(
        destination / "registration.json",
        {
            "primary_registration_sha256": sha256_file(source / "registration.json"),
            "code": code_revision(),
            "catalog_versions": {
                key: versions[key]
                for symbol in funds
                for key in (f"issuer_nav_{symbol}", f"issuer_actions_{symbol}")
            },
            "selection": "all_existing_annual_reports_2021_through_2025",
        },
    )
    # Narrative language and benchmark basis are not converted into derived alpha.
    review = [
        "# 两只红利低波ETF发行人年度披露独立核对",
        "",
        frame.drop(columns=["source_url", "sha256"]).to_markdown(index=False),
        "",
        "比例使用小数。金融权重为各年末指数投资股票/基金净资产；主动投资小额股票另列于原报告，未混入。",
        "日跟踪误差不是年化误差，也不是基金收益波动率。NAV已包含运作费用，账户不重复扣除。",
        "512890的2025年报另称全收益指数上涨5.57%，基金4.74%相差−0.83个百分点；"
        "表内比较基准0.44%与基金相差+4.30个百分点。不同收益口径不能直接解释为管理超额收益。",
        "512890的2024年报叙述将17.84%称为全收益增长，同时表内比较基准也为17.84%；"
        "缺少独立官方全收益日线时，不依据该段文字认证全历史跟踪超额。",
        "各年报于年后披露，年末行业配置只能用于描述与随后可用的信息，不能回填为全年已知权重。",
        "这些材料不能补齐每日历史成分、真实分红削减归因或完整利率暴露因果分析。",
        "同时保留经济总回报和披露口径：前者日因子=(当日NAV+分红)/前日NAV，"
        "后者在分红日使用当日NAV/(前日NAV−分红)。两者不可互换。",
        "515100的2023年差异由此解释：经济总回报约12.62%，披露口径约12.55%。"
        "未修改真实账户、公司行动或放宽容差去贴合报告。",
        "披露算法依据[证监会编报规则第1号第八条]"
        "(https://neris.csrc.gov.cn/falvfagui/rdqsHeader/mainbody?navbarId=2&secFutrsLawId=3acb98d2b17745a19ebb5afbcc52b583)。"
        "真实投资账户继续等待支付日到账后再按规则投入。",
        "未量化披露的跟踪误差保留缺失，不把合同目标上限当作实际跟踪误差。",
    ]
    (destination / "report.md").write_text("\n".join(review) + "\n")
    payloads = {
        p.name: sha256_file(p)
        for p in sorted(destination.iterdir())
        if p.name != "registration.json"
    }
    write_json(destination / "payloads.json", payloads)
    return {
        "directory": str(destination),
        "years": len(rows),
        "annual_nav_checks_passed": bool(frame.nav_reconciled_with_rounding.all()),
        "maximum_annual_difference": float(frame.absolute_return_difference.max()),
    }
