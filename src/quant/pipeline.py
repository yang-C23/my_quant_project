from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

from quant.backtest.engine import run_kdj_forward_return_backtest
from quant.config import load_config
from quant.data.loader import list_symbols_from_db, normalize_symbols, filter_symbols_by_boards
from quant.reporting.report import summarize_overall, summarize_results, write_report

LOGGER = logging.getLogger("quant_pipeline")


def _resolve_symbols(cfg: dict) -> list[str]:
    data_cfg = cfg.get("data", {})
    exclude_boards = set(data_cfg.get("exclude_boards", []) or [])
    symbols = data_cfg.get("symbols") or []
    if symbols:
        return filter_symbols_by_boards(symbols, exclude_boards)

    symbols = list_symbols_from_db(sec_type="stock", exclude_boards=exclude_boards)
    max_stocks = int(data_cfg.get("max_stocks", 0) or 0)
    if max_stocks > 0:
        symbols = symbols[:max_stocks]
    return symbols


def run_pipeline(config_path: str | Path) -> dict:
    cfg = load_config(config_path)
    steps = cfg.get("steps", {})
    backtest_cfg = cfg.get("backtest", {})

    outputs: dict[str, object] = {"config": str(config_path)}

    symbols = _resolve_symbols(cfg)
    if not symbols:
        raise RuntimeError("No symbols resolved for pipeline — check DB connection")

    if steps.get("backtest", False):
        backtest_type = backtest_cfg.get("type", "kdj_forward_return")
        if backtest_type != "kdj_forward_return":
            raise ValueError(f"Unsupported backtest type: {backtest_type}")

        horizons = tuple(int(h) for h in backtest_cfg.get("horizons", [1, 3, 5]))
        kdj_cfg = backtest_cfg.get("kdj", {})

        results = run_kdj_forward_return_backtest(
            symbols=symbols,
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
