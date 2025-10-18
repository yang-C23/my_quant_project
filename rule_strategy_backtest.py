"""
Wrapper script to backtest the proprietary dual-line breath strategy.

Once the actual trading rules are implemented inside
``custom_strategies.dual_line_breath.DualLineBreathStrategy`` this CLI will
invoke the shared backtest engine and produce the usual analytics artefacts.

Example
-------

.. code-block:: bash

    python rule_strategy_backtest.py --symbol 000001.SZ

"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from backtest_engine import (
    BacktestResult,
    configure_logging,
    load_benchmarks,
    parse_strategy_params,
    plot_cumulative_returns,
    run_backtest,
)
from custom_strategies.dual_line_breath import DualLineBreathStrategy

PROJECT_ROOT = Path(__file__).resolve().parent


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest the dual-line breath strategy.")
    parser.add_argument("--symbol", required=True, help="Target ts_code (e.g. 000001.SZ).")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data",
        help="Directory containing Tushare CSV data.",
    )
    parser.add_argument("--cash", type=float, default=100_000.0, help="Initial cash.")
    parser.add_argument("--commission", type=float, default=0.003, help="Commission per trade (0.3%%).")
    parser.add_argument("--slippage", type=float, default=0.0005, help="Slippage percentage.")
    parser.add_argument(
        "--strategy-params",
        nargs="*",
        default=[],
        help="Optional overrides for strategy parameters (key=value).",
    )
    parser.add_argument(
        "--benchmark-symbols",
        nargs="*",
        default=["000852.SH", "000300.SH"],
        help="Benchmarks to display alongside strategy performance.",
    )
    parser.add_argument(
        "--metrics-path",
        type=Path,
        default=PROJECT_ROOT / "backtest_results" / "dual_line_breath_metrics.json",
        help="Path to the metrics JSON output.",
    )
    parser.add_argument(
        "--plot-path",
        type=Path,
        default=PROJECT_ROOT / "backtest_results" / "dual_line_breath_vs_index.png",
        help="Path to the cumulative return plot output.",
    )
    return parser.parse_args(argv)


def save_outputs(result: BacktestResult, metrics_path: Path, plot_path: Path, benchmarks: list[str], data_dir: Path) -> None:
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(result.metrics, ensure_ascii=False, indent=2))
    benchmark_series = load_benchmarks(benchmarks, data_dir)
    if benchmark_series:
        plot_cumulative_returns(result.returns, benchmark_series, plot_path)


def main(argv: Iterable[str] | None = None) -> None:
    configure_logging()
    args = parse_args(argv)
    strategy_params = parse_strategy_params(args.strategy_params)

    result = run_backtest(
        strategy_cls=DualLineBreathStrategy,
        strategy_params=strategy_params,
        data_dir=args.data_dir,
        symbol=args.symbol,
        cash=args.cash,
        commission=args.commission,
        slippage=args.slippage,
    )
    save_outputs(result, args.metrics_path, args.plot_path, args.benchmark_symbols, args.data_dir)


if __name__ == "__main__":
    main()
