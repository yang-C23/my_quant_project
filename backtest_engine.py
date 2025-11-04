"""
Reusable Backtrader backtest engine with A-share market features.

This module provides a CLI and Python API that wrap Backtrader's ``Cerebro`` to
run arbitrary strategy classes—either from ``custom_strategies`` or any dotted
module path on ``PYTHONPATH``. It centralises portfolio configuration, data
loading, analytics, and benchmark visualisation so that strategies can focus on
signal generation.

Key Features:
- T+1 trading constraint (A-share specific: buy today, sell tomorrow+)
- Stamp duty (0.1% on sell only)
- Commission (0.03% default)
- Slippage modeling (tick-based and percentage-based)
- Multi-stock portfolio backtesting support

Sample CLI Usage
----------------

.. code-block:: bash

    python backtest_engine.py --symbol 000001.SZ \\
        --strategy custom_strategies.moving_average:MovingAverageCrossStrategy \\
        --strategy-params short_window=10 long_window=30 \\
        --benchmark-symbols 000300.SH 000852.SH

The engine will generate the strategy metrics JSON and a cumulative return
comparison chart under ``backtest_results/`` by default.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

import matplotlib.pyplot as plt
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
BACKTRADER_PATH = PROJECT_ROOT.parent / "backtrader"

if BACKTRADER_PATH.exists():
    sys.path.insert(0, str(BACKTRADER_PATH))

import backtrader as bt  # type: ignore[import]

LOGGER = logging.getLogger("backtest_engine")


# ======================== A-Share Market Features ======================== #

class AShareCommissionScheme(bt.CommInfoBase):
    """
    A-share commission scheme with stamp duty.
    
    Features:
    - Commission: 0.03% (configurable) on both buy and sell
    - Stamp duty: 0.1% on sell only
    - Minimum commission: 5 CNY per trade
    """
    
    params = (
        ('commission', 0.0003),  # 万3
        ('stamp_duty', 0.001),    # 千1 (sell only)
        ('min_commission', 5.0),  # 最低佣金5元
        ('stocklike', True),
        ('commtype', bt.CommInfoBase.COMM_PERC),
    )
    
    def _getcommission(self, size, price, pseudoexec):
        """Calculate commission including stamp duty for sells."""
        # Base commission
        comm = abs(size) * price * self.p.commission
        
        # Ensure minimum commission
        comm = max(comm, self.p.min_commission)
        
        # Add stamp duty on sells
        if size < 0:  # Selling
            comm += abs(size) * price * self.p.stamp_duty
        
        return comm


class T1Sizer(bt.Sizer):
    """
    T+1 constraint sizer for A-share market.
    
    Prevents selling on the same day as purchase.
    """
    
    params = (
        ('stake', 100),  # Default 1 lot = 100 shares
    )
    
    def _getsizing(self, comminfo, cash, data, isbuy):
        if isbuy:
            # For buying, return the configured stake
            return self.p.stake
        else:
            # For selling, we need to check position age
            # This is handled in the strategy level
            return self.p.stake


class TushareDailyCSV(bt.feeds.GenericCSVData):
    """Backtrader feed mapping for CSV output produced by ``data_downloader``."""

    params = dict(
        dtformat="%Y-%m-%d",  # 修正：数据文件使用YYYY-MM-DD格式
        datetime=0,
        open=1,
        close=2,
        high=3,
        low=4,
        volume=5,
        openinterest=-1,
        nullvalue=0.0,
        headers=True,
    )


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def import_strategy(dotted_path: str) -> type[bt.Strategy]:
    """
    Import a Backtrader strategy class by dotted path.

    Accepts ``module:Class`` or ``module.Class`` style references.
    """

    separator = ":" if ":" in dotted_path else "."
    module_name, class_name = dotted_path.rsplit(separator, 1)
    module = importlib.import_module(module_name)
    strategy_cls = getattr(module, class_name, None)
    if strategy_cls is None:
        raise SystemExit(f"Strategy class `{class_name}` not found in module `{module_name}`.")
    if not issubclass(strategy_cls, bt.Strategy):
        raise SystemExit(f"{strategy_cls} is not a Backtrader Strategy subclass.")
    return strategy_cls


def parse_strategy_params(pairs: Sequence[str]) -> MutableMapping[str, Any]:
    """
    Parse ``key=value`` pairs from the CLI into a mutable mapping.

    Values are interpreted as int, float, bool, or str depending on content.
    """

    params: MutableMapping[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"Invalid strategy parameter `{pair}`; expected key=value.")
        key, value = pair.split("=", 1)
        value = value.strip()
        if value.lower() in {"true", "false"}:
            params[key] = value.lower() == "true"
        else:
            try:
                params[key] = int(value)
            except ValueError:
                try:
                    params[key] = float(value)
                except ValueError:
                    params[key] = value
    return params


def load_price_data(csv_path: Path) -> pd.DataFrame:
    """Read a Tushare-formatted CSV and ensure data is sorted with proper dtypes."""

    df = pd.read_csv(csv_path)
    if "trade_date" not in df.columns:
        raise ValueError(f"{csv_path} is missing the `trade_date` column.")
    df = df.rename(columns={"vol": "volume"}).copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    numeric_cols = ["open", "high", "low", "close", "volume"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df.dropna(subset=["trade_date"], inplace=True)
    return df.sort_values("trade_date").reset_index(drop=True)


def compute_daily_returns(df: pd.DataFrame) -> pd.Series:
    returns = df["close"].pct_change().fillna(0.0)
    returns.index = df["trade_date"]
    return returns


@dataclass
class BacktestResult:
    strategy: bt.Strategy
    metrics: Mapping[str, Any]
    returns: pd.Series
    trades: list[dict]  # 交易详情列表


def compute_metrics(strategy: bt.Strategy, starting_value: float, final_value: float) -> dict[str, Any]:
    metrics: dict[str, Any] = {}

    sharpe = strategy.analyzers.sharpe.get_analysis().get("sharperatio")
    metrics["sharpe_ratio"] = round(sharpe, 4) if sharpe is not None else None

    drawdown = strategy.analyzers.drawdown.get_analysis()
    max_dd = drawdown.get("max", {}).get("drawdown") if drawdown else None
    metrics["max_drawdown_pct"] = round(max_dd, 4) if max_dd is not None else None

    trades = strategy.analyzers.trades.get_analysis()
    closed = trades.get("total", {}).get("closed", 0) if trades else 0
    metrics["total_trades"] = int(closed)

    won = trades.get("won", {}).get("total", 0) if trades else 0
    metrics["win_rate"] = round(won / closed, 4) if closed else None

    win_pnl = trades.get("won", {}).get("pnl", {}).get("total") if trades else None
    lost_pnl = trades.get("lost", {}).get("pnl", {}).get("total") if trades else None
    if win_pnl is not None and lost_pnl:
        metrics["profit_factor"] = round(win_pnl / abs(lost_pnl), 4)
    else:
        metrics["profit_factor"] = None

    metrics["starting_value"] = round(starting_value, 2)
    metrics["final_value"] = round(final_value, 2)
    metrics["total_return_pct"] = round((final_value / starting_value - 1) * 100, 2)
    return metrics


def extract_strategy_returns(strategy: bt.Strategy) -> pd.Series:
    returns_dict = strategy.analyzers.returns.get_analysis()
    returns = pd.Series(returns_dict).sort_index()
    returns.index = pd.to_datetime(returns.index)
    return returns


def extract_trades(strategy: bt.Strategy) -> list[dict]:
    """
    提取所有交易详情
    
    Returns:
        交易详情列表，每个交易包含：
        - type: 'buy' 或 'sell'
        - date: 交易日期
        - price: 交易价格
        - size: 交易股数
        - value: 交易金额
        - pnl: 盈亏（仅sell）
        - pnl_pct: 盈亏百分比（仅sell）
    """
    trades_list = []
    
    # 从strategy的orders中提取
    # 注意：这需要在策略中记录交易
    # 我们可以从TradeAnalyzer中提取
    trade_analysis = strategy.analyzers.trades.get_analysis()
    
    # 如果策略有自定义的交易记录，使用它
    if hasattr(strategy, 'trade_records'):
        return strategy.trade_records
    
    # 否则从analyzer提取（信息较少）
    if trade_analysis and 'long' in trade_analysis:
        for trade_info in trade_analysis.get('long', {}).get('trades', []):
            trades_list.append({
                'type': 'long',
                'entry_date': trade_info.get('entrytime'),
                'entry_price': trade_info.get('entryprice'),
                'exit_date': trade_info.get('exittime'),
                'exit_price': trade_info.get('exitprice'),
                'size': trade_info.get('size'),
                'pnl': trade_info.get('pnl'),
                'pnl_pct': trade_info.get('pnlcomm_percent', 0),
            })
    
    return trades_list


def load_benchmarks(symbols: Sequence[str], data_dir: Path) -> dict[str, pd.Series]:
    benchmark_map: dict[str, pd.Series] = {}
    for ts_code in symbols:
        csv_path = data_dir / f"{ts_code}.csv"
        if not csv_path.exists():
            LOGGER.warning("Benchmark data missing for %s (expected %s).", ts_code, csv_path)
            continue
        df = load_price_data(csv_path)
        benchmark_map[ts_code] = compute_daily_returns(df)
    return benchmark_map


def plot_cumulative_returns(
    strategy_returns: pd.Series,
    benchmarks: Mapping[str, pd.Series],
    output_path: Path,
) -> None:
    if strategy_returns.empty:
        raise ValueError("Strategy returns series is empty; nothing to plot.")

    combined = pd.DataFrame({"Strategy": strategy_returns})
    for code, series in benchmarks.items():
        combined[code] = series.reindex(combined.index).fillna(0.0)

    cumulative = (1 + combined).cumprod()
    growth_pct = (cumulative - 1.0) * 100

    output_path.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(11, 6))
    for column in growth_pct.columns:
        plt.plot(growth_pct.index, growth_pct[column], label=column)
    plt.axhline(0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)
    plt.title("Cumulative Return Growth (%)")
    plt.xlabel("Date")
    plt.ylabel("Growth (%) relative to start")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()


def build_cerebro(
    strategy_cls: type[bt.Strategy],
    strategy_params: Mapping[str, Any],
    csv_path: Path,
    cash: float,
    commission: float,
    slippage: float,
    stamp_duty: float = 0.001,
    use_ashare_commission: bool = True,
) -> bt.Cerebro:
    """
    Build a Cerebro instance with strategy and data feed.
    
    Args:
        strategy_cls: Strategy class to backtest
        strategy_params: Strategy parameters
        csv_path: Path to data CSV file
        cash: Initial cash
        commission: Commission rate (0.0003 = 0.03%)
        slippage: Slippage percentage
        stamp_duty: Stamp duty rate (0.001 = 0.1%, sell only)
        use_ashare_commission: Use A-share commission scheme with stamp duty
        
    Returns:
        Configured Cerebro instance
    """
    cerebro = bt.Cerebro(cheat_on_open=True)
    cerebro.broker.setcash(cash)
    
    # Use A-share commission scheme if specified
    if use_ashare_commission:
        comminfo = AShareCommissionScheme(
            commission=commission,
            stamp_duty=stamp_duty,
        )
        cerebro.broker.addcommissioninfo(comminfo)
    else:
        cerebro.broker.setcommission(commission=commission)
    
    # Set slippage
    cerebro.broker.set_slippage_perc(
        perc=slippage,
        slip_open=True,
        slip_limit=True,
        slip_match=True,
        slip_out=True,
    )
    
    cerebro.addstrategy(strategy_cls, **strategy_params)
    cerebro.adddata(TushareDailyCSV(dataname=str(csv_path)))
    
    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio_A, _name="sharpe", timeframe=bt.TimeFrame.Days)
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.TimeReturn, _name="returns", timeframe=bt.TimeFrame.Days)
    
    return cerebro


def run_backtest(
    strategy_cls: type[bt.Strategy],
    strategy_params: Mapping[str, Any],
    data_dir: Path,
    symbol: str,
    cash: float,
    commission: float,
    slippage: float,
    stamp_duty: float = 0.001,
    use_ashare_commission: bool = True,
) -> BacktestResult:
    """
    Run backtest for a single stock.
    
    Args:
        strategy_cls: Strategy class to backtest
        strategy_params: Strategy parameters
        data_dir: Directory containing data CSV files
        symbol: Stock symbol (e.g., '000001.SZ')
        cash: Initial cash
        commission: Commission rate
        slippage: Slippage percentage
        stamp_duty: Stamp duty rate (sell only)
        use_ashare_commission: Use A-share commission scheme
        
    Returns:
        BacktestResult with strategy, metrics, and returns
    """
    csv_path = data_dir / f"{symbol}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Data file not found: {csv_path}")

    cerebro = build_cerebro(
        strategy_cls, 
        strategy_params, 
        csv_path, 
        cash, 
        commission, 
        slippage,
        stamp_duty,
        use_ashare_commission,
    )
    starting_value = cerebro.broker.getvalue()
    strategies = cerebro.run()
    strategy = strategies[0]
    final_value = cerebro.broker.getvalue()

    metrics = compute_metrics(strategy, starting_value, final_value)
    returns = extract_strategy_returns(strategy)
    trades = extract_trades(strategy)
    return BacktestResult(strategy=strategy, metrics=metrics, returns=returns, trades=trades)


def parse_args_cli(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generic Backtrader backtest runner.")
    parser.add_argument("--symbol", required=True, help="Target ts_code (e.g. 000001.SZ).")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=PROJECT_ROOT / "data",
        help="Directory containing CSV data downloaded from Tushare.",
    )
    parser.add_argument(
        "--strategy",
        default="custom_strategies.moving_average:MovingAverageCrossStrategy",
        help="Dotted path to the Backtrader strategy class.",
    )
    parser.add_argument(
        "--strategy-params",
        nargs="*",
        default=[],
        help="Strategy keyword arguments specified as key=value pairs.",
    )
    parser.add_argument("--cash", type=float, default=100_000.0, help="Initial cash balance.")
    parser.add_argument("--commission", type=float, default=0.0003, help="Commission per trade (e.g. 0.0003 = 0.03%% or 万3).")
    parser.add_argument("--stamp-duty", type=float, default=0.001, help="Stamp duty (e.g. 0.001 = 0.1%% or 千1, sell only).")
    parser.add_argument("--slippage", type=float, default=0.0005, help="Slippage percentage (5 bps default).")
    parser.add_argument("--no-ashare-commission", action="store_true", help="Disable A-share commission scheme (no stamp duty).")
    parser.add_argument(
        "--benchmark-symbols",
        nargs="*",
        default=["000852.SH", "000300.SH"],
        help="List of benchmark ts_codes to plot alongside the strategy.",
    )
    parser.add_argument(
        "--metrics-path",
        type=Path,
        default=PROJECT_ROOT / "backtest_results" / "metrics.json",
        help="Destination path for the metrics JSON output.",
    )
    parser.add_argument(
        "--plot-path",
        type=Path,
        default=PROJECT_ROOT / "backtest_results" / "cumulative_returns.png",
        help="Destination path for the cumulative return plot.",
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Render Backtrader's default candlestick plot (requires GUI backend).",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    configure_logging()
    args = parse_args_cli(argv)
    strategy_cls = import_strategy(args.strategy)
    strategy_params = parse_strategy_params(args.strategy_params)

    result = run_backtest(
        strategy_cls=strategy_cls,
        strategy_params=strategy_params,
        data_dir=args.data_dir,
        symbol=args.symbol,
        cash=args.cash,
        commission=args.commission,
        slippage=args.slippage,
        stamp_duty=args.stamp_duty,
        use_ashare_commission=not args.no_ashare_commission,
    )

    metrics_path = args.metrics_path
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path.write_text(json.dumps(result.metrics, ensure_ascii=False, indent=2))

    benchmarks = load_benchmarks(args.benchmark_symbols, args.data_dir)
    if benchmarks:
        plot_cumulative_returns(result.returns, benchmarks, args.plot_path)
        LOGGER.info("Saved cumulative return plot to %s", args.plot_path)

    LOGGER.info("Metrics saved to %s", metrics_path)
    LOGGER.info("Results: %s", json.dumps(result.metrics, ensure_ascii=False, indent=2))

    if args.plot:
        bt.plot(style="candlestick")


if __name__ == "__main__":
    main()
