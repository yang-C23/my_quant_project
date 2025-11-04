"""
单票回测测试脚本

测试知行双线呼吸策略在不同类型股票上的表现：
- 000001.SZ: 平安银行（银行股，低波动）
- 000002.SZ: 万科A（地产股，中等波动）  
- 002594.SZ: 比亚迪（新能源，高波动）

运行方式:
    python test_dual_line_strategy.py
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from backtest_engine import (
    configure_logging,
    load_benchmarks,
    plot_cumulative_returns,
    run_backtest,
)
from custom_strategies.dual_line_breath import DualLineBreathStrategy

PROJECT_ROOT = Path(__file__).resolve().parent
LOGGER = logging.getLogger("test_dual_line")


def test_symbol(symbol: str, output_prefix: str) -> dict:
    """
    测试单只股票
    
    Args:
        symbol: 股票代码（如 '000001'，不带交易所后缀）
        output_prefix: 输出文件前缀
        
    Returns:
        回测结果字典
    """
    LOGGER.info(f"=" * 70)
    LOGGER.info(f"开始回测: {symbol}")
    LOGGER.info(f"=" * 70)
    
    try:
        result = run_backtest(
            strategy_cls=DualLineBreathStrategy,
            strategy_params={
                'printlog': False,  # 关闭详细日志，只看汇总
            },
            data_dir=PROJECT_ROOT / "data",
            symbol=symbol,  # 直接使用代码，不带.SZ/.SH后缀
            cash=100_000.0,
            commission=0.0003,  # 万3
            slippage=0.0005,    # 5个基点
            stamp_duty=0.001,   # 千1
            use_ashare_commission=True,
        )
        
        # 保存结果
        metrics_path = PROJECT_ROOT / "backtest_results" / f"{output_prefix}_metrics.json"
        plot_path = PROJECT_ROOT / "backtest_results" / f"{output_prefix}_vs_index.png"
        
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        metrics_path.write_text(json.dumps(result.metrics, ensure_ascii=False, indent=2))
        
        # 加载基准数据
        benchmarks = load_benchmarks(["000852.SH", "000300.SH"], PROJECT_ROOT / "data")
        if benchmarks:
            plot_cumulative_returns(result.returns, benchmarks, plot_path)
            LOGGER.info(f"图表已保存: {plot_path}")
        
        LOGGER.info(f"指标已保存: {metrics_path}")
        LOGGER.info(f"")
        LOGGER.info(f"回测结果汇总 - {symbol}:")
        LOGGER.info(f"  起始资金: {result.metrics['starting_value']:.2f}")
        LOGGER.info(f"  期末资金: {result.metrics['final_value']:.2f}")
        LOGGER.info(f"  总收益率: {result.metrics['total_return_pct']:.2f}%")
        LOGGER.info(f"  夏普比率: {result.metrics['sharpe_ratio']}")
        LOGGER.info(f"  最大回撤: {result.metrics['max_drawdown_pct']:.2f}%")
        LOGGER.info(f"  总交易次数: {result.metrics['total_trades']}")
        LOGGER.info(f"  胜率: {result.metrics['win_rate']}")
        LOGGER.info(f"  盈亏比: {result.metrics['profit_factor']}")
        LOGGER.info(f"")
        
        return result.metrics
        
    except FileNotFoundError as e:
        LOGGER.error(f"数据文件不存在: {e}")
        return {}
    except Exception as e:
        LOGGER.error(f"回测失败: {e}", exc_info=True)
        return {}


def main():
    configure_logging()
    
    LOGGER.info("=" * 70)
    LOGGER.info("知行双线呼吸策略 - 单票回测测试")
    LOGGER.info("=" * 70)
    LOGGER.info("")
    
    # 测试三只不同类型的股票（使用纯代码，不带交易所后缀）
    test_stocks = [
        ("000001", "000001_dual_line", "平安银行（银行，低波动）"),
        ("000002", "000002_dual_line", "万科A（地产，中等波动）"),
        ("002594", "002594_dual_line", "比亚迪（新能源，高波动）"),
    ]
    
    results = {}
    for symbol, prefix, description in test_stocks:
        LOGGER.info(f"测试股票: {description}")
        metrics = test_symbol(symbol, prefix)
        if metrics:
            results[symbol] = metrics
    
    # 汇总对比
    LOGGER.info("=" * 70)
    LOGGER.info("所有股票回测结果对比:")
    LOGGER.info("=" * 70)
    LOGGER.info(f"{'股票代码':<15} {'总收益率':<12} {'夏普比率':<12} {'最大回撤':<12} {'交易次数':<10}")
    LOGGER.info("-" * 70)
    
    for symbol, metrics in results.items():
        LOGGER.info(
            f"{symbol:<15} "
            f"{metrics.get('total_return_pct', 0):<12.2f} "
            f"{str(metrics.get('sharpe_ratio', 'N/A')):<12} "
            f"{metrics.get('max_drawdown_pct', 0):<12.2f} "
            f"{metrics.get('total_trades', 0):<10}"
        )
    
    LOGGER.info("=" * 70)
    LOGGER.info("测试完成！结果已保存到 backtest_results/ 目录")
    LOGGER.info("=" * 70)


if __name__ == "__main__":
    main()

