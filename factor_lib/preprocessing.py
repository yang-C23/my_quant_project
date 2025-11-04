"""
因子预处理Pipeline

处理步骤：
1. 极值处理（Mad/Winsorize）
2. 缺失值填充（中位数/均值/行业）
3. 标准化（Z-score/Min-Max）
4. 中性化（行业/市值）

Usage:
    from factor_lib.preprocessing import FactorPreprocessor
    
    preprocessor = FactorPreprocessor()
    clean_factors = preprocessor.fit_transform(
        factor_df,
        industry_map=industry_mapping
    )
"""

from __future__ import annotations

import logging
from typing import Optional, Union

import numpy as np
import pandas as pd
from scipy import stats

LOGGER = logging.getLogger("factor_preprocessing")


class FactorPreprocessor:
    """
    因子预处理器
    
    提供完整的因子预处理流程，确保因子质量。
    """
    
    def __init__(
        self,
        method: str = 'mad',  # 极值处理方法：'mad', 'percentile', 'std'
        fill_method: str = 'median',  # 缺失值填充：'median', 'mean', 'industry'
        standardize: bool = True,
        neutralize: bool = False,
    ):
        self.method = method
        self.fill_method = fill_method
        self.standardize = standardize
        self.neutralize = neutralize
        
        # 存储拟合参数
        self.params_ = {}
    
    def winsorize_mad(
        self,
        data: pd.Series,
        n: float = 3.0,
    ) -> pd.Series:
        """
        MAD（中位数绝对偏差）法去极值
        
        Formula:
            median ± n * MAD
        where:
            MAD = median(|X - median(X)|) * 1.4826
        
        Args:
            data: 因子序列
            n: MAD倍数（通常取3）
        
        Returns:
            去极值后的序列
        """
        median = data.median()
        mad = (data - median).abs().median() * 1.4826  # 1.4826使MAD等价于正态分布的标准差
        
        upper = median + n * mad
        lower = median - n * mad
        
        return data.clip(lower=lower, upper=upper)
    
    def winsorize_percentile(
        self,
        data: pd.Series,
        lower: float = 0.01,
        upper: float = 0.99,
    ) -> pd.Series:
        """
        百分位数法去极值
        
        Args:
            data: 因子序列
            lower: 下分位数（如0.01表示1%）
            upper: 上分位数（如0.99表示99%）
        """
        q_lower = data.quantile(lower)
        q_upper = data.quantile(upper)
        
        return data.clip(lower=q_lower, upper=q_upper)
    
    def winsorize_std(
        self,
        data: pd.Series,
        n: float = 3.0,
    ) -> pd.Series:
        """
        标准差法去极值
        
        Formula:
            mean ± n * std
        """
        mean = data.mean()
        std = data.std()
        
        upper = mean + n * std
        lower = mean - n * std
        
        return data.clip(lower=lower, upper=upper)
    
    def remove_outliers(
        self,
        df: pd.DataFrame,
        method: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        去除极值（对DataFrame的每一列）
        
        Args:
            df: 因子DataFrame (index=date, columns=stock_code)
            method: 去极值方法，None表示使用初始化时的method
        """
        method = method or self.method
        df_clean = df.copy()
        
        for col in df.columns:
            if method == 'mad':
                df_clean[col] = self.winsorize_mad(df[col])
            elif method == 'percentile':
                df_clean[col] = self.winsorize_percentile(df[col])
            elif method == 'std':
                df_clean[col] = self.winsorize_std(df[col])
            else:
                raise ValueError(f"未知的去极值方法: {method}")
        
        return df_clean
    
    def fill_missing(
        self,
        df: pd.DataFrame,
        industry_map: Optional[pd.Series] = None,
        method: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        填充缺失值
        
        Args:
            df: 因子DataFrame
            industry_map: 股票-行业映射 (Series, index=stock_code, values=industry)
            method: 填充方法，None表示使用初始化时的fill_method
        """
        method = method or self.fill_method
        df_filled = df.copy()
        
        if method == 'median':
            # 使用截面中位数填充
            df_filled = df_filled.fillna(df_filled.median())
            
        elif method == 'mean':
            # 使用截面均值填充
            df_filled = df_filled.fillna(df_filled.mean())
            
        elif method == 'industry':
            # 使用行业中位数填充
            if industry_map is None:
                LOGGER.warning("未提供industry_map，使用全市场中位数填充")
                df_filled = df_filled.fillna(df_filled.median())
            else:
                for industry in industry_map.unique():
                    industry_stocks = industry_map[industry_map == industry].index
                    industry_median = df[industry_stocks].median()
                    df_filled[industry_stocks] = df_filled[industry_stocks].fillna(industry_median)
        
        else:
            raise ValueError(f"未知的填充方法: {method}")
        
        # 如果仍有缺失值，用0填充
        df_filled = df_filled.fillna(0)
        
        return df_filled
    
    def standardize_zscore(
        self,
        df: pd.DataFrame,
        industry_map: Optional[pd.Series] = None,
    ) -> pd.DataFrame:
        """
        Z-score标准化
        
        Formula:
            Z = (X - mean) / std
        
        如果提供industry_map，则进行行业内标准化
        """
        df_std = df.copy()
        
        if industry_map is None:
            # 全市场标准化
            mean = df.mean()
            std = df.std()
            df_std = (df - mean) / (std + 1e-10)
        else:
            # 行业内标准化
            for industry in industry_map.unique():
                industry_stocks = industry_map[industry_map == industry].index
                mean = df[industry_stocks].mean()
                std = df[industry_stocks].std()
                df_std[industry_stocks] = (df[industry_stocks] - mean) / (std + 1e-10)
        
        return df_std
    
    def standardize_minmax(
        self,
        df: pd.DataFrame,
        feature_range: tuple = (0, 1),
    ) -> pd.DataFrame:
        """
        Min-Max标准化
        
        Formula:
            X_scaled = (X - X_min) / (X_max - X_min) * (max - min) + min
        """
        df_minmax = df.copy()
        min_val, max_val = feature_range
        
        df_min = df.min()
        df_max = df.max()
        
        df_minmax = (df - df_min) / (df_max - df_min + 1e-10) * (max_val - min_val) + min_val
        
        return df_minmax
    
    def neutralize_industry(
        self,
        df: pd.DataFrame,
        industry_map: pd.Series,
    ) -> pd.DataFrame:
        """
        行业中性化
        
        去除因子中的行业效应：
        Factor_neutral = Factor - Industry_mean(Factor)
        """
        df_neutral = df.copy()
        
        for industry in industry_map.unique():
            industry_stocks = industry_map[industry_map == industry].index
            industry_mean = df[industry_stocks].mean()
            df_neutral[industry_stocks] = df[industry_stocks] - industry_mean
        
        return df_neutral
    
    def neutralize_market_cap(
        self,
        df: pd.DataFrame,
        market_cap: pd.Series,
    ) -> pd.DataFrame:
        """
        市值中性化
        
        通过回归去除市值效应：
        Factor_neutral = Factor - beta * ln(MarketCap)
        
        Args:
            df: 因子DataFrame
            market_cap: 市值序列 (index=stock_code)
        """
        df_neutral = df.copy()
        
        # 对数市值
        log_cap = np.log(market_cap + 1)
        
        # 对每只股票进行回归
        for stock in df.columns:
            if stock not in log_cap.index:
                continue
            
            # 简单线性回归：Factor = alpha + beta * log(Cap) + epsilon
            x = log_cap[stock]
            y = df[stock]
            
            # 去除市值效应
            beta = np.cov(x, y)[0, 1] / (np.var(x) + 1e-10)
            df_neutral[stock] = y - beta * (x - x.mean())
        
        return df_neutral
    
    def fit_transform(
        self,
        df: pd.DataFrame,
        industry_map: Optional[pd.Series] = None,
        market_cap: Optional[pd.Series] = None,
    ) -> pd.DataFrame:
        """
        完整的预处理流程
        
        Args:
            df: 因子DataFrame (rows=time, columns=stock)
            industry_map: 行业映射
            market_cap: 市值数据
        
        Returns:
            预处理后的因子DataFrame
        """
        LOGGER.info(f"开始因子预处理: {df.shape}")
        
        # 1. 去极值
        LOGGER.info("步骤1: 去极值")
        df = self.remove_outliers(df)
        
        # 2. 填充缺失值
        LOGGER.info("步骤2: 填充缺失值")
        df = self.fill_missing(df, industry_map=industry_map)
        
        # 3. 标准化
        if self.standardize:
            LOGGER.info("步骤3: Z-score标准化")
            df = self.standardize_zscore(df, industry_map=industry_map)
        
        # 4. 中性化
        if self.neutralize:
            if industry_map is not None:
                LOGGER.info("步骤4: 行业中性化")
                df = self.neutralize_industry(df, industry_map)
            
            if market_cap is not None:
                LOGGER.info("步骤5: 市值中性化")
                df = self.neutralize_market_cap(df, market_cap)
        
        LOGGER.info(f"预处理完成: {df.shape}")
        
        return df


class CrossSectionalProcessor:
    """
    截面数据处理器
    
    专门用于处理截面因子数据（单个时间点的所有股票）
    """
    
    @staticmethod
    def rank_normalize(data: pd.Series) -> pd.Series:
        """
        排名归一化
        
        将因子值转换为0-1之间的排名百分位
        """
        return data.rank(pct=True)
    
    @staticmethod
    def remove_extreme_percentile(
        data: pd.Series,
        lower: float = 0.01,
        upper: float = 0.99,
    ) -> pd.Series:
        """去除极端百分位"""
        q_lower = data.quantile(lower)
        q_upper = data.quantile(upper)
        return data.clip(lower=q_lower, upper=q_upper)
    
    @staticmethod
    def industry_neutralize(
        factor: pd.Series,
        industry: pd.Series,
    ) -> pd.Series:
        """
        行业中性化（截面）
        
        Args:
            factor: 因子值 (index=stock_code)
            industry: 行业分类 (index=stock_code)
        """
        factor_neutral = factor.copy()
        
        for ind in industry.unique():
            mask = industry == ind
            ind_mean = factor[mask].mean()
            factor_neutral[mask] = factor[mask] - ind_mean
        
        return factor_neutral


def process_factor_panel(
    factor_panel: pd.DataFrame,
    industry_map: Optional[dict[str, pd.Series]] = None,
    method: str = 'mad',
) -> pd.DataFrame:
    """
    处理因子面板数据（时间 x 股票 x 因子）
    
    Args:
        factor_panel: MultiIndex DataFrame (date, stock) x factors
        industry_map: 每个日期的行业映射 {date: industry_series}
        method: 预处理方法
    
    Returns:
        处理后的因子面板
    """
    preprocessor = FactorPreprocessor(method=method)
    
    # 按日期分组处理
    processed_data = []
    
    for date in factor_panel.index.get_level_values(0).unique():
        date_data = factor_panel.loc[date]
        
        # 获取该日期的行业映射
        ind_map = industry_map.get(date) if industry_map else None
        
        # 预处理
        processed = preprocessor.fit_transform(
            date_data.T,  # 转置：股票 x 因子 -> 因子 x 股票
            industry_map=ind_map,
        ).T
        
        # 添加日期索引
        processed['date'] = date
        processed_data.append(processed)
    
    # 合并所有日期
    result = pd.concat(processed_data)
    result = result.set_index(['date', result.index])
    
    return result


if __name__ == "__main__":
    # 测试预处理器
    logging.basicConfig(level=logging.INFO)
    
    # 创建测试数据
    np.random.seed(42)
    dates = pd.date_range('2024-01-01', periods=100)
    stocks = [f'stock_{i}' for i in range(50)]
    
    # 生成带有极值和缺失值的因子数据
    factor_data = np.random.randn(100, 50)
    factor_data[10:15, 5:10] = np.nan  # 添加缺失值
    factor_data[20, 15] = 100  # 添加极值
    
    factor_df = pd.DataFrame(factor_data, index=dates, columns=stocks)
    
    print("原始数据统计:")
    print(factor_df.describe())
    print(f"缺失值: {factor_df.isna().sum().sum()}")
    
    # 预处理
    preprocessor = FactorPreprocessor(method='mad', standardize=True)
    clean_df = preprocessor.fit_transform(factor_df)
    
    print("\n预处理后数据统计:")
    print(clean_df.describe())
    print(f"缺失值: {clean_df.isna().sum().sum()}")

