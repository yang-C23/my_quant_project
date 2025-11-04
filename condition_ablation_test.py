"""
买入条件消融实验
==================
测试每个条件单独和组合的效果

目的：
1. 测试4个买入条件的单独效果
2. 测试不同条件组合的效果
3. 找到最优条件组合
"""

import backtrader as bt
from backtest_engine import run_backtest, BacktestResult
from custom_strategies.dual_line_breath import DualLineBreathStrategy
from datetime import datetime
import pandas as pd
from pathlib import Path
from typing import List, Tuple
import json


class ConditionalStrategy(DualLineBreathStrategy):
    """
    可配置买入条件的策略
    
    用于测试不同条件组合的效果
    """
    
    params = (
        # 继承父类参数
        ('white_period', 10),
        ('j_threshold', 15.0),
        ('volume_ratio_threshold', 2.5),
        ('position_size', 0.10),
        ('printlog', True),
        
        # 条件开关
        ('use_cond_trend', True),        # 是否使用趋势条件
        ('use_cond_activity', True),     # 是否使用活跃度条件
        ('use_cond_entry_j', True),      # 是否使用J值条件
        ('use_cond_price_zone', True),   # 是否使用价格位置条件
    )
    
    def check_buy_conditions(self) -> Tuple[bool, dict]:
        """
        检查买入条件
        
        Returns
        -------
        Tuple[bool, dict]
            (是否满足所有条件, 各条件的状态)
        """
        # 获取指标值
        white = self.white_line[0]
        yellow = self.yellow_line[0]
        j_value = self.kdj.J[0]
        vol_breath = self.volume_breath[0]
        close_price = self.data.close[0]
        
        # 检查各个条件
        conditions = {
            'trend': white > yellow if self.params.use_cond_trend else True,
            'activity': vol_breath > self.params.volume_ratio_threshold if self.params.use_cond_activity else True,
            'entry_j': j_value < self.params.j_threshold if self.params.use_cond_entry_j else True,
            'price_zone': (yellow < close_price < white) if self.params.use_cond_price_zone else True
        }
        
        # 所有启用的条件都满足
        all_satisfied = all(conditions.values())
        
        return all_satisfied, conditions
    
    def next(self):
        """策略主逻辑（重写）"""
        # 检查是否持仓
        if not self.position:
            # 检查买入条件
            should_buy, conditions = self.check_buy_conditions()
            
            if should_buy:
                # 计算可买入的股数
                size = int(self.broker.getcash() * self.params.position_size / self.data.close[0] / 100) * 100
                
                if size >= 100:
                    self.buy(size=size)
                    self.buy_date = self.data.datetime.date(0)
                    self.entry_price = self.data.close[0]
                    self.highest_since_entry = self.data.close[0]
                    
                    if self.params.printlog:
                        print(f'{self.data.datetime.date(0)} BUY: {self.data.close[0]:.2f}, Size: {size}, Conditions: {conditions}')
        
        else:
            # 持仓逻辑（与父类相同）
            # 更新最高价
            if self.data.close[0] > self.highest_since_entry:
                self.highest_since_entry = self.data.close[0]
            
            # 检查止损条件
            white = self.white_line[0]
            yellow = self.yellow_line[0]
            close_price = self.data.close[0]
            
            # 止损1: 收盘价跌破黄线
            stop_loss_yellow = close_price < yellow
            
            # 止损2: 死叉
            death_cross = white < yellow and self.white_line[-1] >= self.yellow_line[-1]
            
            # ATR止盈
            atr_stop = self.atr_trailing_stop.stop_signal[0] if hasattr(self, 'atr_trailing_stop') else False
            
            # T+1限制
            can_sell = (self.data.datetime.date(0) != self.buy_date)
            
            if can_sell and (stop_loss_yellow or death_cross or atr_stop):
                self.sell()
                
                if self.params.printlog:
                    reason = 'Yellow' if stop_loss_yellow else ('Death Cross' if death_cross else 'ATR')
                    print(f'{self.data.datetime.date(0)} SELL: {self.data.close[0]:.2f}, Reason: {reason}')


def test_single_condition(
    stock_code: str,
    condition_name: str,
    fromdate: datetime,
    todate: datetime,
    data_dir: str = "data"
) -> BacktestResult:
    """
    测试单个条件的效果
    
    Parameters
    ----------
    stock_code : str
        股票代码
    condition_name : str
        条件名称: 'trend', 'activity', 'entry_j', 'price_zone'
    fromdate : datetime
        开始日期
    todate : datetime
        结束日期
    data_dir : str
        数据目录
    
    Returns
    -------
    BacktestResult
        回测结果
    """
    # 设置条件（只启用指定条件）
    condition_switches = {
        'use_cond_trend': condition_name == 'trend',
        'use_cond_activity': condition_name == 'activity',
        'use_cond_entry_j': condition_name == 'entry_j',
        'use_cond_price_zone': condition_name == 'price_zone'
    }
    
    # 运行回测
    result = run_backtest(
        symbol=stock_code,
        strategy_class=ConditionalStrategy,
        strategy_params={
            'printlog': False,
            'j_threshold': 15.0,
            'volume_ratio_threshold': 2.5,
            **condition_switches
        },
        fromdate=fromdate,
        todate=todate,
        data_dir=data_dir,
        initial_cash=100000.0
    )
    
    return result


def test_condition_combinations(
    stock_list: List[str],
    fromdate: datetime,
    todate: datetime,
    data_dir: str = "data",
    save_path: str = "backtest_results/condition_ablation"
) -> pd.DataFrame:
    """
    测试所有条件组合
    
    Parameters
    ----------
    stock_list : List[str]
        股票列表
    fromdate : datetime
        开始日期
    todate : datetime
        结束日期
    data_dir : str
        数据目录
    save_path : str
        结果保存路径
    
    Returns
    -------
    pd.DataFrame
        条件组合测试结果
    """
    from itertools import combinations
    
    print("=" * 60)
    print("买入条件消融实验")
    print("=" * 60)
    print(f"测试股票: {stock_list}")
    print(f"测试周期: {fromdate.date()} ~ {todate.date()}")
    print(f"使用最优参数: j_threshold=15.0, volume_ratio=2.5")
    print("=" * 60)
    
    # 所有条件
    all_conditions = ['trend', 'activity', 'entry_j', 'price_zone']
    
    # 生成所有可能的组合（1个、2个、3个、4个条件）
    all_combinations = []
    for r in range(1, len(all_conditions) + 1):
        all_combinations.extend(combinations(all_conditions, r))
    
    results = []
    
    for i, cond_combo in enumerate(all_combinations, 1):
        print(f"\n[{i}/{len(all_combinations)}] 测试组合: {' + '.join(cond_combo)}")
        
        # 设置条件开关
        condition_switches = {
            'use_cond_trend': 'trend' in cond_combo,
            'use_cond_activity': 'activity' in cond_combo,
            'use_cond_entry_j': 'entry_j' in cond_combo,
            'use_cond_price_zone': 'price_zone' in cond_combo
        }
        
        # 对每只股票进行测试
        combo_results = []
        for stock in stock_list:
            try:
                result = run_backtest(
                    symbol=stock,
                    strategy_class=ConditionalStrategy,
                    strategy_params={
                        'printlog': False,
                        'j_threshold': 15.0,
                        'volume_ratio_threshold': 2.5,
                        **condition_switches
                    },
                    fromdate=fromdate,
                    todate=todate,
                    data_dir=data_dir,
                    initial_cash=100000.0,
                    save_result=False
                )
                combo_results.append(result)
            except Exception as e:
                print(f"  {stock} 测试失败: {e}")
                continue
        
        if not combo_results:
            continue
        
        # 汇总结果
        avg_return = sum(r.total_return_pct for r in combo_results) / len(combo_results)
        avg_sharpe = sum(r.sharpe_ratio for r in combo_results if r.sharpe_ratio) / len([r for r in combo_results if r.sharpe_ratio]) if any(r.sharpe_ratio for r in combo_results) else None
        avg_drawdown = sum(r.max_drawdown_pct for r in combo_results) / len(combo_results)
        total_trades = sum(r.total_trades for r in combo_results)
        
        # 计算平均胜率和盈亏比
        win_rates = [r.win_rate for r in combo_results if r.win_rate is not None]
        avg_win_rate = sum(win_rates) / len(win_rates) if win_rates else None
        
        profit_factors = [r.profit_factor for r in combo_results if r.profit_factor is not None]
        avg_profit_factor = sum(profit_factors) / len(profit_factors) if profit_factors else None
        
        result_row = {
            'conditions': ' + '.join(cond_combo),
            'num_conditions': len(cond_combo),
            'avg_return_pct': avg_return,
            'avg_sharpe': avg_sharpe,
            'avg_drawdown_pct': avg_drawdown,
            'total_trades': total_trades,
            'avg_win_rate': avg_win_rate,
            'avg_profit_factor': avg_profit_factor,
            'n_stocks': len(combo_results)
        }
        
        results.append(result_row)
        
        print(f"  平均收益: {avg_return:.2f}%")
        print(f"  平均夏普: {avg_sharpe:.4f}" if avg_sharpe else "  平均夏普: N/A")
        print(f"  总交易次数: {total_trades}")
    
    # 转换为DataFrame
    results_df = pd.DataFrame(results)
    
    # 保存结果
    save_dir = Path(save_path)
    save_dir.mkdir(parents=True, exist_ok=True)
    
    results_df.to_csv(save_dir / 'condition_combinations.csv', index=False)
    
    # 保存最优组合
    print("\n" + "=" * 60)
    print("条件组合分析结果")
    print("=" * 60)
    
    # 按夏普比率排序
    if 'avg_sharpe' in results_df.columns and results_df['avg_sharpe'].notna().any():
        best_by_sharpe = results_df.nlargest(5, 'avg_sharpe')
        print("\nTop 5 by Sharpe Ratio:")
        print(best_by_sharpe[['conditions', 'avg_return_pct', 'avg_sharpe', 'avg_drawdown_pct', 'total_trades']])
    
    # 按收益率排序
    best_by_return = results_df.nlargest(5, 'avg_return_pct')
    print("\nTop 5 by Return:")
    print(best_by_return[['conditions', 'avg_return_pct', 'avg_sharpe', 'avg_drawdown_pct', 'total_trades']])
    
    # 保存摘要
    with open(save_dir / 'summary.txt', 'w', encoding='utf-8') as f:
        f.write("买入条件消融实验摘要\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"测试股票: {stock_list}\n")
        f.write(f"测试周期: {fromdate.date()} ~ {todate.date()}\n")
        f.write(f"参数: j_threshold=15.0, volume_ratio=2.5\n\n")
        f.write("Top 5 by Sharpe Ratio:\n")
        f.write(best_by_sharpe.to_string() + "\n\n")
        f.write("Top 5 by Return:\n")
        f.write(best_by_return.to_string() + "\n")
    
    print(f"\n结果已保存到: {save_dir}")
    
    return results_df


if __name__ == "__main__":
    # 测试股票列表
    test_stocks = ['000001', '000002', '002594', '600519', '000651']
    
    # 测试周期
    fromdate = datetime(2020, 1, 1)
    todate = datetime(2024, 12, 31)
    
    # 运行条件组合测试
    results_df = test_condition_combinations(
        stock_list=test_stocks,
        fromdate=fromdate,
        todate=todate,
        data_dir='data',
        save_path='backtest_results/condition_ablation'
    )

