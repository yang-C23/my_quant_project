from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

from quant.backtest.engine import run_kdj_forward_return_backtest
from quant.config import load_config
from quant.data.downloader import download_kline
from quant.data.loader import (
    list_symbols_from_data_dir,
    load_symbols_from_stocklist,
    normalize_symbols,
)
from quant.data.quality import batch_process_stocks
from quant.reporting.report import summarize_overall, summarize_results, write_report

LOGGER = logging.getLogger("quant_pipeline")


def _resolve_symbols(cfg: dict, data_dir: str | Path) -> list[str]:
    data_cfg = cfg.get("data", {})
    symbols = data_cfg.get("symbols") or []
    if symbols:
        return normalize_symbols(symbols)

    stocklist = data_cfg.get("stocklist")
    if stocklist:
        return load_symbols_from_stocklist(stocklist, limit=int(data_cfg.get("max_stocks", 0) or 0))

    symbols = list_symbols_from_data_dir(data_dir)
    max_stocks = int(data_cfg.get("max_stocks", 0) or 0)
    if max_stocks > 0:
        symbols = symbols[:max_stocks]
    return symbols


def run_pipeline(config_path: str | Path) -> dict:
    cfg = load_config(config_path)
    steps = cfg.get("steps", {})
    data_cfg = cfg.get("data", {})
    quality_cfg = cfg.get("quality", {})
    backtest_cfg = cfg.get("backtest", {})

    data_dir = Path(data_cfg.get("data_dir", "data"))

    outputs: dict[str, object] = {"config": str(config_path)}

    if steps.get("download", False):
        download_cfg = data_cfg.get("download", {})
        start = download_cfg.get("start", "20190101")
        end = download_cfg.get("end", "today")
        if str(start).lower() == "today":
            start = dt.date.today().strftime("%Y%m%d")
        if str(end).lower() == "today":
            end = dt.date.today().strftime("%Y%m%d")

        summary = download_kline(
            stocklist=Path(data_cfg.get("stocklist", "stocklist.csv")),
            start=str(start),
            end=str(end),
            out_dir=data_dir,
            adjust=download_cfg.get("adjust", "qfq"),
            workers=int(download_cfg.get("workers", 3)),
            exclude_boards=set(download_cfg.get("exclude_boards", []) or []),
            overwrite=bool(download_cfg.get("overwrite", False)),
            limit=int(download_cfg.get("limit", 0) or 0),
        )
        outputs["download"] = summary

    symbols = _resolve_symbols(cfg, data_dir=data_dir)
    if not symbols:
        raise RuntimeError("No symbols resolved for pipeline")

    quality_output = None
    if steps.get("quality", False):
        quality_output = quality_cfg.get("output_dir", "data_clean")
        batch_process_stocks(
            symbols=symbols,
            data_dir=data_dir,
            output_dir=quality_output,
            remove_suspension=bool(quality_cfg.get("remove_suspension", True)),
            mark_limit_price=bool(quality_cfg.get("mark_limit_price", True)),
            handle_outliers=bool(quality_cfg.get("handle_outliers", True)),
        )
        outputs["quality"] = {"output_dir": quality_output, "symbols": len(symbols)}

    if steps.get("backtest", False):
        backtest_type = backtest_cfg.get("type", "kdj_forward_return")
        if backtest_type != "kdj_forward_return":
            raise ValueError(f"Unsupported backtest type: {backtest_type}")

        backtest_data_dir = backtest_cfg.get("data_dir")
        if not backtest_data_dir:
            backtest_data_dir = quality_output or data_dir

        horizons = tuple(int(h) for h in backtest_cfg.get("horizons", [1, 3, 5]))
        kdj_cfg = backtest_cfg.get("kdj", {})

        results = run_kdj_forward_return_backtest(
            symbols=symbols,
            data_dir=backtest_data_dir,
            start=backtest_cfg.get("start"),
            end=backtest_cfg.get("end"),
            kdj_n=int(kdj_cfg.get("n", 9)),
            kdj_k=int(kdj_cfg.get("k", 3)),
            kdj_d=int(kdj_cfg.get("d", 3)),
            j_threshold=float(kdj_cfg.get("j_threshold", 0.0)),
            horizons=horizons,
        )

        per_symbol = summarize_results(results, horizons)
        overall = summarize_overall(results, horizons)
        summary = per_symbol
        if not overall.empty:
            summary = overall._append(per_symbol, ignore_index=True)

        report_dir = backtest_cfg.get("report_dir", "backtest_results")
        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = f"pipeline_{backtest_type}_{timestamp}"
        report_paths = write_report(summary, output_dir=report_dir, prefix=prefix)

        outputs["backtest"] = {
            "report": {"csv": str(report_paths["csv"]), "md": str(report_paths["md"])},
            "symbols": len(symbols),
        }

    return outputs
