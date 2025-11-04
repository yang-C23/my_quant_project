"""
因子IC分析模块（Alphalens风格）

功能：
1. IC（Information Coefficient）计算
2. ICIR（Information Ratio）计算
3. 分位数收益分析
4. 因子换手率分析
5. 时间序列IC可视化

Usage:
    from factor_lib.ic_analysis import FactorAnalyzer
    
    analyzer = FactorAnalyzer()
    ic_stats = analyzer.compute_ic(factor_values, forward_returns)
    analyzer.plot_ic_time_series(ic_stats)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

LOGGER = logging.getLogger("ic_analysis")


class FactorAnalyzer:
    """
    因子分析器
    
    提供完整的因子有效性分析工具。
    """
    
    def __init__(self, output_dir: Optional[str | Path] = None):
        self.output_dir = Path(output_dir) if output_dir else None
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def compute_forward_returns(
        self,
        prices: pd.DataFrame,
        periods: list[int] = [1, 5, 10, 20],
    ) -> dict[int, pd.DataFrame]:
        """
        计算未来收益率
        
        Args:
            prices: 价格DataFrame (index=date, columns=stock)
            periods: 计算周期列表
        
        Returns:
            {period: forward_returns_df} 字典
        """
        forward_returns = {}
        
        for period in periods:
            # 计算未来period日收益率
            fwd_ret = prices.shift(-period) / prices - 1
            forward_returns[period] = fwd_ret
        
        return forward_returns
    
    def compute_ic(
        self,
        factor: pd.Series,
        forward_return: pd.Series,
        method: str = 'spearman',
    ) -> float:
        """
        计算单期IC
        
        Args:
            factor: 因子值 (index=stock_code)
            forward_return: 未来收益率 (index=stock_code)
            method: 相关系数方法 ('pearson' 或 'spearman')
        
        Returns:
            IC值
        """
        # 对齐数据
        common_index = factor.index.intersection(forward_return.index)
        factor = factor.loc[common_index]
        forward_return = forward_return.loc[common_index]
        
        # 去除NaN
        valid_mask = factor.notna() & forward_return.notna()
        factor = factor[valid_mask]
        forward_return = forward_return[valid_mask]
        
        if len(factor) < 3:
            return np.nan
        
        # 计算相关系数
        if method == 'spearman':
            ic, _ = stats.spearmanr(factor, forward_return)
        elif method == 'pearson':
            ic, _ = stats.pearsonr(factor, forward_return)
        else:
            raise ValueError(f"未知的相关系数方法: {method}")
        
        return ic
    
    def compute_ic_series(
        self,
        factor_panel: pd.DataFrame,
        return_panel: pd.DataFrame,
        method: str = 'spearman',
    ) -> pd.Series:
        """
        计算IC时间序列
        
        Args:
            factor_panel: 因子面板 (index=date, columns=stock)
            return_panel: 收益率面板 (index=date, columns=stock)
            method: 相关系数方法
        
        Returns:
            IC时间序列 (index=date)
        """
        ic_series = []
        dates = factor_panel.index.intersection(return_panel.index)
        
        for date in dates:
            factor_values = factor_panel.loc[date]
            return_values = return_panel.loc[date]
            
            ic = self.compute_ic(factor_values, return_values, method=method)
            ic_series.append({'date': date, 'ic': ic})
        
        ic_df = pd.DataFrame(ic_series).set_index('date')
        return ic_df['ic']
    
    def compute_ic_stats(
        self,
        ic_series: pd.Series,
    ) -> dict:
        """
        计算IC统计指标
        
        Returns:
            包含IC均值、标准差、IR、胜率等指标的字典
        """
        ic_mean = ic_series.mean()
        ic_std = ic_series.std()
        ic_ir = ic_mean / (ic_std + 1e-10)  # Information Ratio
        ic_positive_rate = (ic_series > 0).sum() / len(ic_series)
        
        stats_dict = {
            'IC_mean': ic_mean,
            'IC_std': ic_std,
            'IC_IR': ic_ir,
            'IC_positive_rate': ic_positive_rate,
            'IC_min': ic_series.min(),
            'IC_max': ic_series.max(),
            'IC_median': ic_series.median(),
        }
        
        return stats_dict
    
    def quantile_analysis(
        self,
        factor_panel: pd.DataFrame,
        return_panel: pd.DataFrame,
        n_quantiles: int = 5,
    ) -> pd.DataFrame:
        """
        分位数收益分析
        
        将因子值分为N组，计算各组的平均收益率。
        
        Args:
            factor_panel: 因子面板
            return_panel: 收益率面板
            n_quantiles: 分组数
        
        Returns:
            各分位数组的平均收益率 (index=date, columns=quantile)
        """
        quantile_returns = []
        dates = factor_panel.index.intersection(return_panel.index)
        
        for date in dates:
            factor_values = factor_panel.loc[date]
            return_values = return_panel.loc[date]
            
            # 去除NaN
            valid_mask = factor_values.notna() & return_values.notna()
            factor_values = factor_values[valid_mask]
            return_values = return_values[valid_mask]
            
            if len(factor_values) < n_quantiles:
                continue
            
            # 分位数分组
            quantiles = pd.qcut(factor_values, q=n_quantiles, labels=False, duplicates='drop')
            
            # 计算各组平均收益
            quantile_ret = {}
            for q in range(n_quantiles):
                mask = quantiles == q
                if mask.sum() > 0:
                    quantile_ret[f'Q{q+1}'] = return_values[mask].mean()
                else:
                    quantile_ret[f'Q{q+1}'] = np.nan
            
            quantile_ret['date'] = date
            quantile_returns.append(quantile_ret)
        
        result = pd.DataFrame(quantile_returns).set_index('date')
        
        # 计算多空收益（Q5 - Q1）
        if 'Q5' in result.columns and 'Q1' in result.columns:
            result['Long_Short'] = result['Q5'] - result['Q1']
        
        return result
    
    def compute_turnover(
        self,
        factor_panel: pd.DataFrame,
        n_quantiles: int = 5,
        quantile_to_track: int = 5,
    ) -> pd.Series:
        """
        计算因子换手率
        
        换手率 = 相邻两期分位数组成分股票的变化比例
        
        Args:
            factor_panel: 因子面板
            n_quantiles: 分位数
            quantile_to_track: 跟踪的分位数组（通常是Q5，即最高组）
        
        Returns:
            换手率时间序列
        """
        turnover_series = []
        dates = sorted(factor_panel.index)
        
        prev_stocks = None
        
        for date in dates:
            factor_values = factor_panel.loc[date].dropna()
            
            if len(factor_values) < n_quantiles:
                continue
            
            # 分位数分组
            quantiles = pd.qcut(factor_values, q=n_quantiles, labels=False, duplicates='drop')
            
            # 获取目标分位数的股票
            current_stocks = set(factor_values[quantiles == (quantile_to_track - 1)].index)
            
            if prev_stocks is not None:
                # 计算换手率
                intersection = current_stocks & prev_stocks
                union = current_stocks | prev_stocks
                
                if len(prev_stocks) > 0:
                    turnover = 1 - len(intersection) / len(prev_stocks)
                else:
                    turnover = np.nan
                
                turnover_series.append({'date': date, 'turnover': turnover})
            
            prev_stocks = current_stocks
        
        result = pd.DataFrame(turnover_series).set_index('date')
        return result['turnover']
    
    def plot_ic_time_series(
        self,
        ic_series: pd.Series,
        title: str = "IC Time Series",
        save_path: Optional[Path] = None,
    ) -> None:
        """绘制IC时间序列图"""
        fig, axes = plt.subplots(2, 1, figsize=(12, 8))
        
        # IC时间序列
        axes[0].plot(ic_series.index, ic_series.values, label='IC', alpha=0.7)
        axes[0].axhline(y=0, color='r', linestyle='--', alpha=0.5)
        axes[0].axhline(y=ic_series.mean(), color='g', linestyle='--', alpha=0.5, label=f'Mean IC={ic_series.mean():.4f}')
        axes[0].set_title(title)
        axes[0].set_xlabel('Date')
        axes[0].set_ylabel('IC')
        axes[0].legend()
        axes[0].grid(alpha=0.3)
        
        # IC累计曲线
        ic_cumsum = ic_series.cumsum()
        axes[1].plot(ic_cumsum.index, ic_cumsum.values, label='Cumulative IC', color='blue')
        axes[1].set_title('Cumulative IC')
        axes[1].set_xlabel('Date')
        axes[1].set_ylabel('Cumulative IC')
        axes[1].legend()
        axes[1].grid(alpha=0.3)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            LOGGER.info(f"图表已保存: {save_path}")
        else:
            plt.show()
        
        plt.close()
    
    def plot_quantile_returns(
        self,
        quantile_returns: pd.DataFrame,
        title: str = "Quantile Returns",
        save_path: Optional[Path] = None,
    ) -> None:
        """绘制分位数收益图"""
        fig, axes = plt.subplots(2, 1, figsize=(12, 8))
        
        # 各分位数累计收益
        cumulative_returns = (1 + quantile_returns).cumprod() - 1
        
        for col in cumulative_returns.columns:
            if col != 'Long_Short':
                axes[0].plot(cumulative_returns.index, cumulative_returns[col], label=col, alpha=0.7)
        
        axes[0].set_title(f'{title} - Cumulative Returns by Quantile')
        axes[0].set_xlabel('Date')
        axes[0].set_ylabel('Cumulative Return')
        axes[0].legend()
        axes[0].grid(alpha=0.3)
        
        # 多空收益
        if 'Long_Short' in cumulative_returns.columns:
            axes[1].plot(
                cumulative_returns.index,
                cumulative_returns['Long_Short'],
                label='Long-Short',
                color='purple',
                linewidth=2,
            )
            axes[1].axhline(y=0, color='r', linestyle='--', alpha=0.5)
            axes[1].set_title('Long-Short Portfolio Cumulative Return')
            axes[1].set_xlabel('Date')
            axes[1].set_ylabel('Cumulative Return')
            axes[1].legend()
            axes[1].grid(alpha=0.3)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
            LOGGER.info(f"图表已保存: {save_path}")
        else:
            plt.show()
        
        plt.close()
    
    def generate_report(
        self,
        factor_name: str,
        factor_panel: pd.DataFrame,
        price_panel: pd.DataFrame,
        periods: list[int] = [5, 10, 20],
    ) -> dict:
        """
        生成完整的因子分析报告
        
        Args:
            factor_name: 因子名称
            factor_panel: 因子面板
            price_panel: 价格面板
            periods: 预测周期列表
        
        Returns:
            包含所有分析结果的字典
        """
        LOGGER.info(f"开始分析因子: {factor_name}")
        
        report = {
            'factor_name': factor_name,
            'ic_stats': {},
            'quantile_analysis': {},
            'turnover': {},
        }
        
        # 计算未来收益率
        forward_returns = self.compute_forward_returns(price_panel, periods=periods)
        
        # 对每个周期进行分析
        for period in periods:
            LOGGER.info(f"  分析周期: {period}日")
            
            return_panel = forward_returns[period]
            
            # IC分析
            ic_series = self.compute_ic_series(factor_panel, return_panel)
            ic_stats = self.compute_ic_stats(ic_series)
            report['ic_stats'][period] = ic_stats
            
            LOGGER.info(f"    IC均值: {ic_stats['IC_mean']:.4f}")
            LOGGER.info(f"    IC_IR: {ic_stats['IC_IR']:.4f}")
            LOGGER.info(f"    IC胜率: {ic_stats['IC_positive_rate']:.2%}")
            
            # 分位数分析
            quantile_returns = self.quantile_analysis(factor_panel, return_panel, n_quantiles=5)
            report['quantile_analysis'][period] = quantile_returns
            
            # 绘图
            if self.output_dir:
                # IC时间序列图
                ic_plot_path = self.output_dir / f"{factor_name}_IC_{period}d.png"
                self.plot_ic_time_series(
                    ic_series,
                    title=f"{factor_name} - IC Time Series ({period}d)",
                    save_path=ic_plot_path,
                )
                
                # 分位数收益图
                quantile_plot_path = self.output_dir / f"{factor_name}_Quantile_{period}d.png"
                self.plot_quantile_returns(
                    quantile_returns,
                    title=f"{factor_name} ({period}d)",
                    save_path=quantile_plot_path,
                )
        
        # 换手率分析
        turnover = self.compute_turnover(factor_panel, n_quantiles=5, quantile_to_track=5)
        report['turnover'] = {
            'mean': turnover.mean(),
            'std': turnover.std(),
            'series': turnover,
        }
        
        LOGGER.info(f"因子分析完成: {factor_name}")
        
        return report


if __name__ == "__main__":
    # 测试IC分析
    logging.basicConfig(level=logging.INFO)
    
    # 创建测试数据
    np.random.seed(42)
    dates = pd.date_range('2024-01-01', periods=100)
    stocks = [f'stock_{i}' for i in range(50)]
    
    # 生成因子数据（有一定预测能力）
    factor_data = np.random.randn(100, 50)
    factor_df = pd.DataFrame(factor_data, index=dates, columns=stocks)
    
    # 生成价格数据（部分受因子影响）
    price_data = 100 * np.exp(np.cumsum(0.001 * factor_data + 0.01 * np.random.randn(100, 50), axis=0))
    price_df = pd.DataFrame(price_data, index=dates, columns=stocks)
    
    # 分析
    analyzer = FactorAnalyzer(output_dir='factor_analysis_test')
    report = analyzer.generate_report(
        factor_name='test_factor',
        factor_panel=factor_df,
        price_panel=price_df,
        periods=[5, 10],
    )
    
    print("\n因子分析报告:")
    for period, stats in report['ic_stats'].items():
        print(f"\n{period}日预测:")
        for key, value in stats.items():
            print(f"  {key}: {value:.4f}")

