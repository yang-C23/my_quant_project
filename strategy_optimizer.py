"""
策略参数优化模块

功能：
1. 网格搜索优化
2. 遗传算法优化
3. Walk-forward分析
4. 动态参数调整（K-means聚类）
5. 参数敏感性分析

Usage:
    from strategy_optimizer import StrategyOptimizer
    
    optimizer = StrategyOptimizer(strategy_cls=DualLineBreathStrategy)
    best_params = optimizer.grid_search(
        param_grid={'j_threshold': [5, 10, 13, 15, 20]},
        symbols=['000001', '000002'],
        objective='sharpe'
    )
"""

from __future__ import annotations

import logging
from itertools import product
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

from backtest_engine import run_backtest

LOGGER = logging.getLogger("strategy_optimizer")


class StrategyOptimizer:
    """
    策略参数优化器
    
    支持多种优化方法和目标函数。
    """
    
    def __init__(
        self,
        strategy_cls,
        data_dir: str | Path = 'data',
        cash: float = 100_000.0,
    ):
        self.strategy_cls = strategy_cls
        self.data_dir = Path(data_dir)
        self.cash = cash
        
        self.results: List[Dict[str, Any]] = []
    
    def _run_single_backtest(
        self,
        symbol: str,
        strategy_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """运行单次回测"""
        try:
            result = run_backtest(
                strategy_cls=self.strategy_cls,
                strategy_params=strategy_params,
                data_dir=self.data_dir,
                symbol=symbol,
                cash=self.cash,
                commission=0.0003,
                slippage=0.0005,
                stamp_duty=0.001,
                use_ashare_commission=True,
            )
            return result.metrics
        except Exception as e:
            LOGGER.error(f"回测失败 {symbol} with params {strategy_params}: {e}")
            return {}
    
    def grid_search(
        self,
        param_grid: Dict[str, List[Any]],
        symbols: List[str],
        objective: str = 'sharpe',  # 'sharpe', 'total_return', 'win_rate', 'profit_factor'
        min_trades: int = 5,  # 最少交易次数阈值
    ) -> Tuple[Dict[str, Any], pd.DataFrame]:
        """
        网格搜索优化
        
        Args:
            param_grid: 参数网格，例如 {'j_threshold': [5, 10, 15], 'volume_ratio_threshold': [2.5, 3.5]}
            symbols: 测试股票列表
            objective: 优化目标
            min_trades: 最少交易次数（过滤交易太少的参数组合）
        
        Returns:
            (最优参数, 所有结果DataFrame)
        """
        LOGGER.info("开始网格搜索优化...")
        LOGGER.info(f"参数网格: {param_grid}")
        LOGGER.info(f"测试股票: {len(symbols)} 只")
        
        # 生成所有参数组合
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        param_combinations = list(product(*param_values))
        
        LOGGER.info(f"总参数组合数: {len(param_combinations)}")
        
        results = []
        
        for i, param_combo in enumerate(param_combinations):
            params = dict(zip(param_names, param_combo))
            
            LOGGER.info(f"测试参数组合 {i+1}/{len(param_combinations)}: {params}")
            
            # 在所有股票上测试
            combo_results = []
            for symbol in symbols:
                metrics = self._run_single_backtest(symbol, params)
                if metrics:
                    combo_results.append(metrics)
            
            if not combo_results:
                continue
            
            # 汇总结果
            avg_sharpe = np.mean([m.get('sharpe_ratio', 0) or 0 for m in combo_results])
            avg_return = np.mean([m.get('total_return_pct', 0) for m in combo_results])
            avg_win_rate = np.mean([m.get('win_rate', 0) or 0 for m in combo_results])
            avg_profit_factor = np.mean([m.get('profit_factor', 0) or 0 for m in combo_results])
            total_trades = sum([m.get('total_trades', 0) for m in combo_results])
            
            result_summary = {
                **params,
                'avg_sharpe': avg_sharpe,
                'avg_return': avg_return,
                'avg_win_rate': avg_win_rate,
                'avg_profit_factor': avg_profit_factor,
                'total_trades': total_trades,
                'n_stocks': len(combo_results),
            }
            
            results.append(result_summary)
            
            LOGGER.info(
                f"  结果: Sharpe={avg_sharpe:.3f}, Return={avg_return:.2f}%, "
                f"Win Rate={avg_win_rate:.2%}, Trades={total_trades}"
            )
        
        # 转换为DataFrame
        results_df = pd.DataFrame(results)
        
        # 过滤交易次数太少的组合
        results_df = results_df[results_df['total_trades'] >= min_trades]
        
        if results_df.empty:
            LOGGER.warning("所有参数组合的交易次数都少于阈值！")
            return {}, pd.DataFrame()
        
        # 根据目标函数排序
        objective_map = {
            'sharpe': 'avg_sharpe',
            'total_return': 'avg_return',
            'win_rate': 'avg_win_rate',
            'profit_factor': 'avg_profit_factor',
        }
        
        sort_col = objective_map.get(objective, 'avg_sharpe')
        results_df = results_df.sort_values(sort_col, ascending=False)
        
        # 获取最优参数
        best_row = results_df.iloc[0]
        best_params = {k: best_row[k] for k in param_names}
        
        LOGGER.info("=" * 60)
        LOGGER.info("优化完成！")
        LOGGER.info(f"最优参数: {best_params}")
        LOGGER.info(f"平均Sharpe: {best_row['avg_sharpe']:.3f}")
        LOGGER.info(f"平均收益率: {best_row['avg_return']:.2f}%")
        LOGGER.info(f"平均胜率: {best_row['avg_win_rate']:.2%}")
        LOGGER.info(f"总交易次数: {best_row['total_trades']}")
        LOGGER.info("=" * 60)
        
        return best_params, results_df
    
    def compute_dynamic_j_threshold(
        self,
        j_values: pd.Series,
        method: str = 'kmeans',
        n_clusters: int = 3,
    ) -> float:
        """
        动态计算J值阈值（K-means聚类）
        
        Args:
            j_values: J值序列
            method: 方法 ('kmeans', 'percentile')
            n_clusters: 聚类数（通常3个：超卖、正常、超买）
        
        Returns:
            动态阈值
        """
        j_clean = j_values.dropna()
        
        if len(j_clean) < 10:
            return 13  # 默认值
        
        if method == 'kmeans':
            # K-means聚类
            X = j_clean.values.reshape(-1, 1)
            kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
            kmeans.fit(X)
            
            # 获取聚类中心并排序
            centers = sorted(kmeans.cluster_centers_.flatten())
            
            # 返回最低聚类的上界（超卖阈值）
            lowest_cluster_label = np.argmin(kmeans.cluster_centers_)
            threshold = centers[0] + (centers[1] - centers[0]) * 0.5
            
            LOGGER.info(f"K-means聚类中心: {centers}")
            LOGGER.info(f"动态J阈值: {threshold:.2f}")
            
            return threshold
            
        elif method == 'percentile':
            # 使用百分位数
            threshold = j_clean.quantile(0.05)  # 5%分位数
            LOGGER.info(f"百分位数J阈值: {threshold:.2f}")
            return threshold
        
        else:
            raise ValueError(f"未知方法: {method}")
    
    def walk_forward_analysis(
        self,
        param_grid: Dict[str, List[Any]],
        symbols: List[str],
        train_period: int = 252,  # 训练期（交易日）
        test_period: int = 63,    # 测试期（交易日）
        step: int = 63,           # 滚动步长
    ) -> pd.DataFrame:
        """
        Walk-forward分析
        
        滚动训练和测试，避免过拟合。
        
        Args:
            param_grid: 参数网格
            symbols: 测试股票
            train_period: 训练期长度
            test_period: 测试期长度
            step: 滚动步长
        
        Returns:
            每个测试窗口的最优参数和表现
        """
        LOGGER.info("开始Walk-forward分析...")
        
        # TODO: 实现完整的walk-forward逻辑
        # 这需要按时间窗口分割数据，在训练窗口优化参数，在测试窗口验证
        
        raise NotImplementedError("Walk-forward分析待实现")
    
    def parameter_sensitivity_analysis(
        self,
        base_params: Dict[str, Any],
        param_to_test: str,
        test_range: List[Any],
        symbols: List[str],
        objective: str = 'sharpe',
    ) -> pd.DataFrame:
        """
        参数敏感性分析
        
        固定其他参数，只变化一个参数，观察对结果的影响。
        
        Args:
            base_params: 基准参数
            param_to_test: 要测试的参数名
            test_range: 测试值范围
            symbols: 测试股票
            objective: 目标函数
        
        Returns:
            敏感性分析结果DataFrame
        """
        LOGGER.info(f"参数敏感性分析: {param_to_test}")
        
        results = []
        
        for value in test_range:
            test_params = base_params.copy()
            test_params[param_to_test] = value
            
            # 在所有股票上测试
            combo_results = []
            for symbol in symbols:
                metrics = self._run_single_backtest(symbol, test_params)
                if metrics:
                    combo_results.append(metrics)
            
            if not combo_results:
                continue
            
            # 汇总
            avg_metric = np.mean([m.get(objective.replace('avg_', ''), 0) or 0 for m in combo_results])
            
            results.append({
                param_to_test: value,
                f'avg_{objective}': avg_metric,
            })
            
            LOGGER.info(f"  {param_to_test}={value}: {objective}={avg_metric:.3f}")
        
        return pd.DataFrame(results)


class MarketRegimeDetector:
    """
    市场形态检测器（大盘趋势判断）
    
    用于识别市场处于牛市、熊市还是震荡市，
    并据此动态调整策略参数。
    """
    
    def __init__(
        self,
        index_symbol: str = '000001',  # 使用上证指数或其他大盘指数
        short_ma: int = 20,
        long_ma: int = 60,
    ):
        self.index_symbol = index_symbol
        self.short_ma = short_ma
        self.long_ma = long_ma
    
    def detect_regime(
        self,
        index_data: pd.DataFrame,
    ) -> pd.Series:
        """
        检测市场形态
        
        Args:
            index_data: 指数数据 (必须包含close列)
        
        Returns:
            市场形态序列: 'bull'（牛市）, 'bear'（熊市）, 'sideways'（震荡）
        """
        close = index_data['close']
        
        # 计算短期和长期均线
        ma_short = close.rolling(self.short_ma).mean()
        ma_long = close.rolling(self.long_ma).mean()
        
        # 计算价格相对位置
        price_position = (close - ma_long) / ma_long
        
        # 计算趋势强度（短均线与长均线的距离）
        trend_strength = (ma_short - ma_long) / ma_long
        
        # 市场形态判断
        regime = pd.Series(index=close.index, dtype=str)
        
        # 牛市：价格在长期均线之上 且 短期均线在长期均线之上
        bull_mask = (price_position > 0.05) & (trend_strength > 0.02)
        regime[bull_mask] = 'bull'
        
        # 熊市：价格在长期均线之下 且 短期均线在长期均线之下
        bear_mask = (price_position < -0.05) & (trend_strength < -0.02)
        regime[bear_mask] = 'bear'
        
        # 震荡市：其他情况
        regime[(~bull_mask) & (~bear_mask)] = 'sideways'
        
        return regime
    
    def get_regime_adjusted_params(
        self,
        current_regime: str,
        base_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        根据市场形态调整策略参数
        
        Args:
            current_regime: 当前市场形态
            base_params: 基准参数
        
        Returns:
            调整后的参数
        """
        adjusted_params = base_params.copy()
        
        if current_regime == 'bull':
            # 牛市：放宽买入条件，提高持仓
            adjusted_params['j_threshold'] = adjusted_params.get('j_threshold', 13) * 1.5
            adjusted_params['position_pct'] = adjusted_params.get('position_pct', 0.1) * 1.2
            adjusted_params['volume_ratio_threshold'] = adjusted_params.get('volume_ratio_threshold', 3.5) * 0.8
            LOGGER.info("牛市模式：放宽买入条件")
            
        elif current_regime == 'bear':
            # 熊市：收紧条件，降低仓位
            adjusted_params['j_threshold'] = adjusted_params.get('j_threshold', 13) * 0.7
            adjusted_params['position_pct'] = adjusted_params.get('position_pct', 0.1) * 0.5
            adjusted_params['volume_ratio_threshold'] = adjusted_params.get('volume_ratio_threshold', 3.5) * 1.2
            LOGGER.info("熊市模式：收紧买入条件，降低仓位")
            
        else:  # sideways
            # 震荡市：使用标准参数
            LOGGER.info("震荡市模式：使用标准参数")
        
        return adjusted_params


if __name__ == "__main__":
    # 测试参数优化
    logging.basicConfig(level=logging.INFO)
    
    from custom_strategies.dual_line_breath import DualLineBreathStrategy
    
    optimizer = StrategyOptimizer(
        strategy_cls=DualLineBreathStrategy,
        data_dir='data',
    )
    
    # 网格搜索
    param_grid = {
        'j_threshold': [5, 10, 13, 15, 20],
        'volume_ratio_threshold': [2.5, 3.0, 3.5, 4.0],
    }
    
    test_symbols = ['000001', '000002', '002594']
    
    best_params, results_df = optimizer.grid_search(
        param_grid=param_grid,
        symbols=test_symbols,
        objective='sharpe',
        min_trades=1,  # 降低阈值用于测试
    )
    
    print("\n最优参数:", best_params)
    print("\n前5个最优组合:")
    print(results_df.head())

