"""
Launcher for machine-learning driven strategies under Backtrader.

The default implementation simply loads a persisted model and is meant to be
extended with feature engineering and signal generation logic. It relies on the
shared :mod:`backtest_engine` module to keep analytics consistent with rule-
based strategies.

Example
-------

.. code-block:: bash

    python ml_strategy_backtest.py --symbol 000001.SZ \\
        --model-path models/random_forest.pkl

"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import backtrader as bt  # type: ignore[import]
import joblib

from backtest_engine import (
    BacktestResult,
    configure_logging,
    load_benchmarks,
    parse_strategy_params,
    plot_cumulative_returns,
    run_backtest,
)


class MLSignalStrategy(bt.Strategy):
    """
    Placeholder ML strategy that loads a pre-trained model from disk.

    Replace the ``next`` method with actual feature extraction and order
    placement. The class is intentionally barebones to emphasise the integration
    points with Backtrader.
    """

    params = dict(model_path=Path("models/random_forest.pkl"))

    def __init__(self) -> None:
        self.model = joblib.load(self.params.model_path)

    def next(self) -> None:
        raise NotImplementedError("Implement ML signal inference inside `next`.")


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an ML-driven Backtrader strategy.")
    parser.add_argument("--symbol", required=True, help="Target ts_code (e.g. 000001.SZ).")
    parser.add_argument("--model-path", type=Path, default=Path("models/random_forest.pkl"))
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Directory containing CSV data.",
    )
    parser.add_argument("--cash", type=float, default=100_000.0, help="Initial cash.")
    parser.add_argument("--commission", type=float, default=0.003, help="Commission per trade.")
    parser.add_argument("--slippage", type=float, default=0.0005, help="Slippage percentage.")
    parser.add_argument(
        "--strategy-params",
        nargs="*",
        default=[],
        help="Additional strategy parameters (key=value).",
    )
    parser.add_argument(
        "--benchmark-symbols",
        nargs="*",
        default=["000852.SH", "000300.SH"],
        help="Benchmarks for cumulative return comparison.",
    )
    parser.add_argument(
        "--metrics-path",
        type=Path,
        default=Path("backtest_results/ml_strategy_metrics.json"),
        help="Path for metrics JSON output.",
    )
    parser.add_argument(
        "--plot-path",
        type=Path,
        default=Path("backtest_results/ml_strategy_vs_index.png"),
        help="Path for cumulative return plot output.",
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
    strategy_params.setdefault("model_path", args.model_path)

    result = run_backtest(
        strategy_cls=MLSignalStrategy,
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
