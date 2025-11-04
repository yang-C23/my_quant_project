"""
全市场回测脚本
==============
在整个股票池中进行轮动选股回测

使用最优参数运行完整的市场回测
"""

import argparse
from datetime import datetime
from pathlib import Path
import pandas as pd
from portfolio_backtest import run_portfolio_backtest
from custom_strategies.dual_line_breath import DualLineBreathStrategy
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('full_market_backtest.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='全市场回测')
    
    parser.add_argument('--stocklist', type=str, default='stocklist.csv',
                       help='股票列表文件')
    parser.add_argument('--start-date', type=str, default='2020-01-01',
                       help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, default='2024-12-31',
                       help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('--initial-cash', type=float, default=1000000.0,
                       help='初始资金')
    parser.add_argument('--max-positions', type=int, default=10,
                       help='最大持仓数')
    parser.add_argument('--data-dir', type=str, default='data',
                       help='数据目录')
    parser.add_argument('--result-dir', type=str, default='backtest_results/full_market',
                       help='结果保存目录')
    
    # 策略参数（使用最优参数）
    parser.add_argument('--j-threshold', type=float, default=15.0,
                       help='J值阈值（最优参数）')
    parser.add_argument('--volume-ratio', type=float, default=2.5,
                       help='成交量呼吸度阈值（最优参数）')
    parser.add_argument('--white-period', type=int, default=10,
                       help='白线周期')
    parser.add_argument('--position-size', type=float, default=0.10,
                       help='单个股票仓位比例')
    
    # 止损策略
    parser.add_argument('--stop-loss-type', type=str, default='combined',
                       choices=['conservative', 'moderate', 'aggressive', 'atr', 'combined'],
                       help='止损策略类型')
    
    return parser.parse_args()


def filter_stock_list(stocklist_file: str, min_data_points: int = 500) -> list:
    """
    过滤股票列表，移除数据不足的股票
    
    Parameters
    ----------
    stocklist_file : str
        股票列表文件
    min_data_points : int
        最小数据点数
    
    Returns
    -------
    list
        有效的股票代码列表
    """
    df = pd.read_csv(stocklist_file)
    
    if 'ts_code' not in df.columns:
        raise ValueError("Stock list must contain 'ts_code' column")
    
    # 提取股票代码
    stock_codes = df['ts_code'].apply(
        lambda x: x.split('.')[0] if isinstance(x, str) else x
    ).tolist()
    
    # 过滤数据不足的股票
    data_dir = Path('data')
    valid_stocks = []
    
    logger.info(f"开始筛选股票，共 {len(stock_codes)} 只...")
    
    for stock in stock_codes:
        csv_file = data_dir / f"{stock}.csv"
        if csv_file.exists():
            try:
                data = pd.read_csv(csv_file)
                if len(data) >= min_data_points:
                    valid_stocks.append(stock)
            except Exception as e:
                logger.warning(f"{stock} 数据读取失败: {e}")
    
    logger.info(f"筛选完成，有效股票: {len(valid_stocks)}/{len(stock_codes)}")
    
    return valid_stocks


def run_market_backtest_by_sector(
    stocklist_file: str,
    fromdate: datetime,
    todate: datetime,
    args
):
    """
    按行业分组运行回测
    
    Parameters
    ----------
    stocklist_file : str
        股票列表文件
    fromdate : datetime
        开始日期
    todate : datetime
        结束日期
    args
        命令行参数
    """
    # 读取股票列表
    df = pd.read_csv(stocklist_file)
    
    if 'industry' not in df.columns:
        logger.warning("股票列表中没有行业信息，将所有股票视为一个组")
        sectors = {'全市场': df['ts_code'].tolist()}
    else:
        # 按行业分组
        sectors = df.groupby('industry')['ts_code'].apply(list).to_dict()
    
    logger.info(f"共 {len(sectors)} 个行业/板块")
    
    all_results = []
    
    for sector_name, stocks in sectors.items():
        logger.info(f"\n{'='*60}")
        logger.info(f"回测行业: {sector_name} ({len(stocks)} 只股票)")
        logger.info(f"{'='*60}")
        
        # 过滤有效股票
        valid_stocks = []
        data_dir = Path(args.data_dir)
        
        for stock in stocks:
            stock_code = stock.split('.')[0] if '.' in stock else stock
            csv_file = data_dir / f"{stock_code}.csv"
            if csv_file.exists():
                valid_stocks.append(stock_code)
        
        if len(valid_stocks) < 3:
            logger.warning(f"{sector_name} 有效股票数不足3只，跳过")
            continue
        
        logger.info(f"有效股票: {len(valid_stocks)}/{len(stocks)}")
        
        # 创建临时股票列表
        temp_stocklist = Path(args.result_dir) / f'temp_{sector_name}.csv'
        temp_stocklist.parent.mkdir(parents=True, exist_ok=True)
        
        temp_df = pd.DataFrame({
            'ts_code': [f"{s}.SH" if s.startswith('6') else f"{s}.SZ" for s in valid_stocks],
            'industry': sector_name
        })
        temp_df.to_csv(temp_stocklist, index=False)
        
        try:
            # 运行回测
            result = run_portfolio_backtest(
                stock_list_file=str(temp_stocklist),
                strategy_class=DualLineBreathStrategy,
                strategy_params={
                    'printlog': False,
                    'white_period': args.white_period,
                    'j_threshold': args.j_threshold,
                    'volume_ratio_threshold': args.volume_ratio,
                    'position_size': args.position_size
                },
                fromdate=fromdate,
                todate=todate,
                data_dir=args.data_dir,
                result_dir=f"{args.result_dir}/{sector_name}",
                initial_cash=args.initial_cash,
                max_positions=args.max_positions,
                save_results=True,
                plot_results=False  # 不绘图以节省时间
            )
            
            # 保存结果
            all_results.append({
                'sector': sector_name,
                'n_stocks': len(valid_stocks),
                'total_return_pct': result.total_return_pct,
                'sharpe_ratio': result.sharpe_ratio,
                'max_drawdown_pct': result.max_drawdown_pct,
                'total_trades': result.total_trades,
                'win_rate': result.win_rate,
                'profit_factor': result.profit_factor
            })
            
        except Exception as e:
            logger.error(f"{sector_name} 回测失败: {e}")
            continue
        
        finally:
            # 清理临时文件
            if temp_stocklist.exists():
                temp_stocklist.unlink()
    
    # 保存汇总结果
    if all_results:
        summary_df = pd.DataFrame(all_results)
        summary_file = Path(args.result_dir) / 'sector_summary.csv'
        summary_df.to_csv(summary_file, index=False)
        
        logger.info(f"\n{'='*60}")
        logger.info("全市场回测完成")
        logger.info(f"{'='*60}")
        logger.info(f"\n行业回测汇总:\n{summary_df.to_string(index=False)}")
        logger.info(f"\n结果已保存到: {summary_file}")


def main():
    """主函数"""
    args = parse_args()
    
    logger.info("=" * 60)
    logger.info("全市场回测")
    logger.info("=" * 60)
    logger.info(f"股票列表: {args.stocklist}")
    logger.info(f"回测周期: {args.start_date} ~ {args.end_date}")
    logger.info(f"初始资金: {args.initial_cash:,.0f}")
    logger.info(f"最大持仓: {args.max_positions}")
    logger.info(f"策略参数: J={args.j_threshold}, Vol={args.volume_ratio}")
    logger.info(f"止损策略: {args.stop_loss_type}")
    logger.info("=" * 60)
    
    # 解析日期
    fromdate = datetime.strptime(args.start_date, '%Y-%m-%d')
    todate = datetime.strptime(args.end_date, '%Y-%m-%d')
    
    # 方式1: 全市场一起回测（推荐用于日常测试）
    logger.info("\n方式1: 全市场组合回测...")
    
    try:
        result = run_portfolio_backtest(
            stock_list_file=args.stocklist,
            strategy_class=DualLineBreathStrategy,
            strategy_params={
                'printlog': False,
                'white_period': args.white_period,
                'j_threshold': args.j_threshold,
                'volume_ratio_threshold': args.volume_ratio,
                'position_size': args.position_size
            },
            fromdate=fromdate,
            todate=todate,
            data_dir=args.data_dir,
            result_dir=args.result_dir,
            initial_cash=args.initial_cash,
            max_positions=args.max_positions,
            save_results=True,
            plot_results=True
        )
        
        logger.info("\n" + "=" * 60)
        logger.info("回测结果")
        logger.info("=" * 60)
        logger.info(f"总收益率: {result.total_return_pct:.2f}%")
        logger.info(f"夏普比率: {result.sharpe_ratio:.4f}" if result.sharpe_ratio else "夏普比率: N/A")
        logger.info(f"最大回撤: {result.max_drawdown_pct:.2f}%")
        logger.info(f"总交易次数: {result.total_trades}")
        if result.win_rate:
            logger.info(f"胜率: {result.win_rate:.2%}")
        if result.profit_factor:
            logger.info(f"盈亏比: {result.profit_factor:.4f}")
    
    except Exception as e:
        logger.error(f"全市场回测失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 方式2: 按行业分组回测（可选，耗时较长）
    # logger.info("\n方式2: 按行业分组回测...")
    # run_market_backtest_by_sector(args.stocklist, fromdate, todate, args)


if __name__ == "__main__":
    main()

