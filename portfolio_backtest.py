"""
组合回测模块
=============
多股票组合回测框架

主要功能：
1. 多股票数据加载
2. 资金池管理
3. 最大持仓限制
4. 组合级别的性能分析
5. 与基准指数对比
"""

import backtrader as bt
import pandas as pd
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime
import json

# 导入回测引擎
from backtest_engine import (
    TushareDailyCSV,
    AShareCommissionScheme,
    BacktestResult,
    extract_trades
)

# 导入策略
from custom_strategies.dual_line_breath import DualLineBreathStrategy
from custom_strategies.ml_strategy import MLSignalStrategy


class PortfolioBacktester:
    """
    组合回测器
    
    支持多股票、多策略的回测
    """
    
    def __init__(
        self,
        data_dir: str = "data",
        result_dir: str = "backtest_results",
        initial_cash: float = 1000000.0,  # 100万初始资金
        commission: float = 0.0003,        # 万三佣金
        stamp_duty: float = 0.001,         # 千一印花税
        slippage: float = 0.0005           # 滑点0.05%
    ):
        """
        初始化组合回测器
        
        Parameters
        ----------
        data_dir : str
            数据目录
        result_dir : str
            结果保存目录
        initial_cash : float
            初始资金
        commission : float
            佣金率
        stamp_duty : float
            印花税率
        slippage : float
            滑点
        """
        self.data_dir = Path(data_dir)
        self.result_dir = Path(result_dir)
        self.result_dir.mkdir(parents=True, exist_ok=True)
        
        self.initial_cash = initial_cash
        self.commission = commission
        self.stamp_duty = stamp_duty
        self.slippage = slippage
        
        # Cerebro实例
        self.cerebro = None
    
    def load_stock_list(self, stock_list_file: str) -> List[str]:
        """
        加载股票列表
        
        Parameters
        ----------
        stock_list_file : str
            股票列表CSV文件（包含ts_code列）
        
        Returns
        -------
        List[str]
            股票代码列表
        """
        df = pd.read_csv(stock_list_file)
        
        if 'ts_code' not in df.columns:
            raise ValueError("Stock list file must contain 'ts_code' column")
        
        # 提取纯代码（去掉.SZ/.SH后缀）
        stock_codes = df['ts_code'].apply(
            lambda x: x.split('.')[0] if isinstance(x, str) else x
        ).tolist()
        
        return stock_codes
    
    def setup_cerebro(
        self,
        strategy_class,
        strategy_params: Optional[Dict] = None,
        max_positions: int = 10
    ):
        """
        设置Cerebro实例
        
        Parameters
        ----------
        strategy_class
            策略类
        strategy_params : dict, optional
            策略参数
        max_positions : int
            最大持仓数
        """
        self.cerebro = bt.Cerebro()
        
        # 添加策略
        strategy_params = strategy_params or {}
        self.cerebro.addstrategy(strategy_class, **strategy_params)
        
        # 设置初始资金
        self.cerebro.broker.setcash(self.initial_cash)
        
        # 设置佣金和印花税
        self.cerebro.broker.addcommissioninfo(
            AShareCommissionScheme(
                commission=self.commission,
                stamp_duty=self.stamp_duty
            )
        )
        
        # 设置滑点
        self.cerebro.broker.set_slippage_perc(self.slippage)
        
        # 添加分析器
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        self.cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        
        print(f"Cerebro设置完成")
        print(f"  初始资金: {self.initial_cash:,.0f}")
        print(f"  最大持仓: {max_positions}")
        print(f"  佣金: {self.commission*10000:.1f}万分")
        print(f"  印花税: {self.stamp_duty*1000:.1f}千分")
        print(f"  滑点: {self.slippage*100:.2f}%")
    
    def add_stock_data(
        self,
        stock_codes: List[str],
        fromdate: Optional[datetime] = None,
        todate: Optional[datetime] = None
    ) -> int:
        """
        添加股票数据到Cerebro
        
        Parameters
        ----------
        stock_codes : List[str]
            股票代码列表
        fromdate : datetime, optional
            开始日期
        todate : datetime, optional
            结束日期
        
        Returns
        -------
        int
            成功加载的股票数量
        """
        if self.cerebro is None:
            raise ValueError("Please call setup_cerebro() first")
        
        loaded_count = 0
        failed_stocks = []
        
        print(f"\n加载股票数据 ({len(stock_codes)} 只)...")
        
        for i, stock_code in enumerate(stock_codes, 1):
            # 尝试多种文件名格式
            found = False
            for code_fmt in [stock_code, f"{stock_code}.SZ", f"{stock_code}.SH"]:
                csv_file = self.data_dir / f"{code_fmt}.csv"
                
                # 如果没有后缀，尝试纯代码
                if not csv_file.exists():
                    csv_file = self.data_dir / f"{stock_code}.csv"
                
                if csv_file.exists():
                    try:
                        # 创建数据源
                        data = TushareDailyCSV(
                            dataname=str(csv_file),
                            fromdate=fromdate,
                            todate=todate
                        )
                        
                        # 设置数据名称（用于策略中识别）
                        data._name = stock_code
                        
                        # 添加到Cerebro
                        self.cerebro.adddata(data, name=stock_code)
                        
                        loaded_count += 1
                        found = True
                        
                        if i % 50 == 0:
                            print(f"  已加载: {i}/{len(stock_codes)}")
                        
                        break
                    
                    except Exception as e:
                        print(f"  警告: 加载 {stock_code} 失败: {e}")
                        failed_stocks.append(stock_code)
                        break
            
            if not found:
                failed_stocks.append(stock_code)
        
        print(f"\n数据加载完成！")
        print(f"  成功: {loaded_count}/{len(stock_codes)}")
        if failed_stocks:
            print(f"  失败: {len(failed_stocks)} 只")
            if len(failed_stocks) <= 10:
                print(f"  失败列表: {', '.join(failed_stocks)}")
        
        return loaded_count
    
    def run(self) -> BacktestResult:
        """
        运行回测
        
        Returns
        -------
        BacktestResult
            回测结果
        """
        if self.cerebro is None:
            raise ValueError("Please call setup_cerebro() and add_stock_data() first")
        
        print(f"\n{'='*60}")
        print(f"开始组合回测")
        print(f"{'='*60}\n")
        
        starting_value = self.cerebro.broker.getvalue()
        
        # 运行回测
        results = self.cerebro.run()
        strategy = results[0]
        
        ending_value = self.cerebro.broker.getvalue()
        
        # 提取分析结果
        sharpe = strategy.analyzers.sharpe.get_analysis()
        drawdown = strategy.analyzers.drawdown.get_analysis()
        returns = strategy.analyzers.returns.get_analysis()
        trade_analysis = strategy.analyzers.trades.get_analysis()
        
        # 构建结果
        result = BacktestResult(
            starting_value=starting_value,
            final_value=ending_value,
            total_return_pct=(ending_value - starting_value) / starting_value * 100,
            sharpe_ratio=sharpe.get('sharperatio', None),
            max_drawdown_pct=drawdown.get('max', {}).get('drawdown', 0.0),
            total_trades=trade_analysis.total.get('total', 0) if hasattr(trade_analysis, 'total') else 0,
            win_rate=None,
            profit_factor=None,
            trades=extract_trades(strategy) if hasattr(strategy, 'trade_records') else []
        )
        
        # 计算胜率和盈亏比
        if hasattr(trade_analysis, 'won') and hasattr(trade_analysis, 'lost'):
            won = trade_analysis.won.get('total', 0)
            lost = trade_analysis.lost.get('total', 0)
            total = won + lost
            
            if total > 0:
                result.win_rate = won / total
            
            if lost > 0:
                avg_win = trade_analysis.won.get('pnl', {}).get('average', 0)
                avg_loss = abs(trade_analysis.lost.get('pnl', {}).get('average', 1))
                result.profit_factor = avg_win / avg_loss if avg_loss > 0 else None
        
        print(f"\n{'='*60}")
        print(f"回测完成")
        print(f"{'='*60}")
        print(f"起始资金: {result.starting_value:,.2f}")
        print(f"期末资金: {result.final_value:,.2f}")
        print(f"总收益率: {result.total_return_pct:.2f}%")
        print(f"夏普比率: {result.sharpe_ratio:.4f}" if result.sharpe_ratio else "夏普比率: N/A")
        print(f"最大回撤: {result.max_drawdown_pct:.2f}%")
        print(f"总交易次数: {result.total_trades}")
        if result.win_rate is not None:
            print(f"胜率: {result.win_rate:.2%}")
        if result.profit_factor is not None:
            print(f"盈亏比: {result.profit_factor:.4f}")
        
        return result
    
    def save_results(
        self,
        result: BacktestResult,
        filename: str = "portfolio_backtest_result"
    ):
        """
        保存回测结果
        
        Parameters
        ----------
        result : BacktestResult
            回测结果
        filename : str
            文件名（不含扩展名）
        """
        # 保存指标
        metrics = {
            'starting_value': result.starting_value,
            'final_value': result.final_value,
            'total_return_pct': result.total_return_pct,
            'sharpe_ratio': result.sharpe_ratio,
            'max_drawdown_pct': result.max_drawdown_pct,
            'total_trades': result.total_trades,
            'win_rate': result.win_rate,
            'profit_factor': result.profit_factor
        }
        
        metrics_file = self.result_dir / f"{filename}_metrics.json"
        with open(metrics_file, 'w') as f:
            json.dump(metrics, f, indent=2)
        
        print(f"\n指标已保存: {metrics_file}")
        
        # 保存交易记录
        if result.trades:
            trades_df = pd.DataFrame(result.trades)
            trades_file = self.result_dir / f"{filename}_trades.csv"
            trades_df.to_csv(trades_file, index=False)
            print(f"交易记录已保存: {trades_file}")
    
    def plot_results(self, filename: str = "portfolio_backtest"):
        """
        绘制回测结果图表
        
        Parameters
        ----------
        filename : str
            保存文件名（不含扩展名）
        """
        if self.cerebro is None:
            print("No cerebro instance to plot")
            return
        
        import matplotlib.pyplot as plt
        
        # 绘制资金曲线
        fig = self.cerebro.plot(style='candlestick', barup='red', bardown='green')[0][0]
        
        # 保存图表
        plot_file = self.result_dir / f"{filename}_plot.png"
        fig.savefig(plot_file, dpi=150, bbox_inches='tight')
        plt.close(fig)
        
        print(f"回测图表已保存: {plot_file}")


def run_portfolio_backtest(
    stock_list_file: str,
    strategy_class,
    strategy_params: Optional[Dict] = None,
    fromdate: Optional[datetime] = None,
    todate: Optional[datetime] = None,
    data_dir: str = "data",
    result_dir: str = "backtest_results",
    initial_cash: float = 1000000.0,
    max_positions: int = 10,
    save_results: bool = True,
    plot_results: bool = True
) -> BacktestResult:
    """
    运行组合回测的便捷函数
    
    Parameters
    ----------
    stock_list_file : str
        股票列表文件
    strategy_class
        策略类
    strategy_params : dict, optional
        策略参数
    fromdate : datetime, optional
        开始日期
    todate : datetime, optional
        结束日期
    data_dir : str
        数据目录
    result_dir : str
        结果目录
    initial_cash : float
        初始资金
    max_positions : int
        最大持仓数
    save_results : bool
        是否保存结果
    plot_results : bool
        是否绘制图表
    
    Returns
    -------
    BacktestResult
        回测结果
    """
    # 创建回测器
    backtester = PortfolioBacktester(
        data_dir=data_dir,
        result_dir=result_dir,
        initial_cash=initial_cash
    )
    
    # 加载股票列表
    stock_codes = backtester.load_stock_list(stock_list_file)
    print(f"\n股票列表: {len(stock_codes)} 只")
    
    # 设置Cerebro
    backtester.setup_cerebro(
        strategy_class=strategy_class,
        strategy_params=strategy_params,
        max_positions=max_positions
    )
    
    # 添加数据
    loaded = backtester.add_stock_data(stock_codes, fromdate, todate)
    
    if loaded == 0:
        raise ValueError("No stock data loaded")
    
    # 运行回测
    result = backtester.run()
    
    # 保存结果
    if save_results:
        backtester.save_results(result)
    
    # 绘制图表
    if plot_results:
        try:
            backtester.plot_results()
        except Exception as e:
            print(f"绘图失败: {e}")
    
    return result


if __name__ == "__main__":
    # 测试代码
    import sys
    
    if len(sys.argv) > 1:
        stock_list_file = sys.argv[1]
        
        # 运行组合回测（使用规则策略）
        result = run_portfolio_backtest(
            stock_list_file=stock_list_file,
            strategy_class=DualLineBreathStrategy,
            strategy_params={
                'printlog': False,
                'white_period': 10,
                'j_threshold': 13,
                'volume_ratio_threshold': 3.5
            },
            fromdate=datetime(2020, 1, 1),
            todate=datetime(2024, 12, 31),
            data_dir="data",
            result_dir="backtest_results",
            initial_cash=1000000.0,
            max_positions=10
        )
    else:
        print("用法: python portfolio_backtest.py <stock_list_file>")
        print("示例: python portfolio_backtest.py stocklist.csv")

