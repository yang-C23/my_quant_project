"""
数据质量检查与预处理

功能：
1. 异常值检测与处理
2. 停牌日过滤
3. 涨跌停标记
4. 复权检查
5. 缺失值处理

Usage:
    from data_quality import DataQualityChecker
    
    checker = DataQualityChecker(data_dir='data')
    clean_data = checker.process_stock('000001')
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd

LOGGER = logging.getLogger("data_quality")


class DataQualityChecker:
    """
    数据质量检查器
    
    检查项：
    - 价格异常值（如负数、极端涨跌幅）
    - 成交量异常（零成交量、异常放量）
    - 停牌检测
    - 涨跌停标记
    - 数据完整性
    """
    
    def __init__(
        self,
        data_dir: str | Path,
        max_daily_return: float = 0.20,  # A股单日最大涨跌幅20%（ST股除外）
        min_price: float = 0.01,
        max_price: float = 10000.0,
    ):
        self.data_dir = Path(data_dir)
        self.max_daily_return = max_daily_return
        self.min_price = min_price
        self.max_price = max_price
    
    def load_stock_data(self, symbol: str) -> pd.DataFrame:
        """加载单只股票数据"""
        csv_path = self.data_dir / f"{symbol}.csv"
        if not csv_path.exists():
            raise FileNotFoundError(f"数据文件不存在: {csv_path}")
        
        df = pd.read_csv(csv_path)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').reset_index(drop=True)
        
        # 数据类型转换
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        return df
    
    def check_price_validity(self, df: pd.DataFrame) -> pd.DataFrame:
        """检查价格有效性"""
        issues = pd.DataFrame(index=df.index)
        
        # 1. 价格为负或零
        issues['negative_price'] = (
            (df['close'] <= 0) | 
            (df['open'] <= 0) | 
            (df['high'] <= 0) | 
            (df['low'] <= 0)
        )
        
        # 2. 价格超出合理范围
        issues['price_out_of_range'] = (
            (df['close'] < self.min_price) | 
            (df['close'] > self.max_price)
        )
        
        # 3. OHLC关系异常
        issues['ohlc_invalid'] = (
            (df['high'] < df['low']) |
            (df['high'] < df['open']) |
            (df['high'] < df['close']) |
            (df['low'] > df['open']) |
            (df['low'] > df['close'])
        )
        
        # 4. 极端涨跌幅
        returns = df['close'].pct_change()
        issues['extreme_return'] = (
            (returns.abs() > self.max_daily_return) & 
            (returns.notna())
        )
        
        return issues
    
    def detect_suspension(self, df: pd.DataFrame) -> pd.Series:
        """
        检测停牌日
        
        特征：
        - 成交量为0
        - 或OHLC四价相同
        """
        zero_volume = df['volume'] == 0
        flat_price = (
            (df['open'] == df['close']) & 
            (df['close'] == df['high']) & 
            (df['high'] == df['low'])
        )
        
        return zero_volume | flat_price
    
    def detect_limit_price(self, df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
        """
        检测涨跌停
        
        Returns:
            (upper_limit, lower_limit): 涨停和跌停标记
        
        Note:
            A股涨跌停幅度：
            - 普通股票：±10%
            - ST股票：±5%
            - 科创板/创业板：±20%
            这里使用±9.9%作为阈值（保守估计）
        """
        returns = df['close'].pct_change()
        
        # 涨停：涨幅接近10%
        upper_limit = (returns > 0.099) & (returns < 0.101)
        
        # 跌停：跌幅接近10%
        lower_limit = (returns < -0.099) & (returns > -0.101)
        
        return upper_limit, lower_limit
    
    def handle_outliers(
        self,
        df: pd.DataFrame,
        columns: list[str] = ['close', 'volume'],
        method: str = 'clip',
        std_threshold: float = 5.0,
    ) -> pd.DataFrame:
        """
        处理异常值
        
        Args:
            df: 数据DataFrame
            columns: 需要处理的列
            method: 处理方法 ('clip' 或 'remove')
            std_threshold: 标准差阈值
        
        Returns:
            处理后的DataFrame
        """
        df = df.copy()
        
        for col in columns:
            if col not in df.columns:
                continue
            
            # 计算均值和标准差
            mean = df[col].mean()
            std = df[col].std()
            
            # 定义异常值范围
            lower_bound = mean - std_threshold * std
            upper_bound = mean + std_threshold * std
            
            if method == 'clip':
                # 裁剪到合理范围
                df[col] = df[col].clip(lower=lower_bound, upper=upper_bound)
            elif method == 'remove':
                # 标记为NaN
                outliers = (df[col] < lower_bound) | (df[col] > upper_bound)
                df.loc[outliers, col] = np.nan
        
        return df
    
    def fill_missing_values(
        self,
        df: pd.DataFrame,
        method: str = 'ffill',
    ) -> pd.DataFrame:
        """
        填充缺失值
        
        Args:
            method: 填充方法
                - 'ffill': 向前填充
                - 'bfill': 向后填充
                - 'interpolate': 线性插值
        """
        df = df.copy()
        
        if method == 'ffill':
            df = df.fillna(method='ffill')
        elif method == 'bfill':
            df = df.fillna(method='bfill')
        elif method == 'interpolate':
            df = df.interpolate(method='linear')
        
        return df
    
    def process_stock(
        self,
        symbol: str,
        remove_suspension: bool = True,
        mark_limit_price: bool = True,
        handle_outliers: bool = True,
    ) -> pd.DataFrame:
        """
        完整的数据质量处理流程
        
        Args:
            symbol: 股票代码
            remove_suspension: 是否移除停牌日
            mark_limit_price: 是否标记涨跌停
            handle_outliers: 是否处理异常值
        
        Returns:
            处理后的DataFrame，包含额外的质量标记列
        """
        LOGGER.info(f"处理股票数据: {symbol}")
        
        # 1. 加载数据
        df = self.load_stock_data(symbol)
        original_len = len(df)
        
        # 2. 价格有效性检查
        issues = self.check_price_validity(df)
        invalid_rows = issues.any(axis=1)
        
        if invalid_rows.sum() > 0:
            LOGGER.warning(
                f"{symbol}: 发现 {invalid_rows.sum()} 条无效数据 "
                f"({invalid_rows.sum() / len(df) * 100:.2f}%)"
            )
            # 移除无效行
            df = df[~invalid_rows].copy()
        
        # 3. 停牌检测
        df['is_suspended'] = self.detect_suspension(df)
        suspension_count = df['is_suspended'].sum()
        
        if suspension_count > 0:
            LOGGER.info(f"{symbol}: 检测到 {suspension_count} 个停牌日")
            if remove_suspension:
                df = df[~df['is_suspended']].copy()
                LOGGER.info(f"{symbol}: 已移除停牌日")
        
        # 4. 涨跌停标记
        if mark_limit_price:
            upper_limit, lower_limit = self.detect_limit_price(df)
            df['is_upper_limit'] = upper_limit
            df['is_lower_limit'] = lower_limit
            
            limit_count = (upper_limit | lower_limit).sum()
            if limit_count > 0:
                LOGGER.info(
                    f"{symbol}: 检测到 {limit_count} 个涨跌停日 "
                    f"(涨停 {upper_limit.sum()}, 跌停 {lower_limit.sum()})"
                )
        
        # 5. 异常值处理
        if handle_outliers:
            df = self.handle_outliers(
                df,
                columns=['close', 'volume'],
                method='clip',
                std_threshold=5.0,
            )
        
        # 6. 填充缺失值
        df = self.fill_missing_values(df, method='ffill')
        
        # 7. 重置索引
        df = df.reset_index(drop=True)
        
        final_len = len(df)
        removed_pct = (original_len - final_len) / original_len * 100
        
        LOGGER.info(
            f"{symbol}: 处理完成 "
            f"(原始 {original_len} 条 -> 最终 {final_len} 条, "
            f"移除 {removed_pct:.2f}%)"
        )
        
        return df
    
    def generate_quality_report(self, symbol: str) -> dict:
        """
        生成数据质量报告
        
        Returns:
            包含各项质量指标的字典
        """
        df = self.load_stock_data(symbol)
        
        report = {
            'symbol': symbol,
            'total_rows': len(df),
            'date_range': {
                'start': df['date'].min().strftime('%Y-%m-%d'),
                'end': df['date'].max().strftime('%Y-%m-%d'),
            },
            'missing_values': {},
            'price_issues': {},
            'suspension_days': 0,
            'limit_price_days': {},
        }
        
        # 缺失值统计
        for col in ['open', 'high', 'low', 'close', 'volume']:
            missing = df[col].isna().sum()
            report['missing_values'][col] = {
                'count': int(missing),
                'percentage': float(missing / len(df) * 100),
            }
        
        # 价格问题统计
        issues = self.check_price_validity(df)
        for issue_type in issues.columns:
            count = issues[issue_type].sum()
            report['price_issues'][issue_type] = {
                'count': int(count),
                'percentage': float(count / len(df) * 100),
            }
        
        # 停牌统计
        suspension = self.detect_suspension(df)
        report['suspension_days'] = int(suspension.sum())
        
        # 涨跌停统计
        upper_limit, lower_limit = self.detect_limit_price(df)
        report['limit_price_days'] = {
            'upper_limit': int(upper_limit.sum()),
            'lower_limit': int(lower_limit.sum()),
        }
        
        return report


def batch_process_stocks(
    symbols: list[str],
    data_dir: str | Path,
    output_dir: Optional[str | Path] = None,
) -> dict[str, pd.DataFrame]:
    """
    批量处理多只股票数据
    
    Args:
        symbols: 股票代码列表
        data_dir: 原始数据目录
        output_dir: 输出目录，None表示不保存
    
    Returns:
        {symbol: cleaned_df} 字典
    """
    checker = DataQualityChecker(data_dir=data_dir)
    results = {}
    
    for symbol in symbols:
        try:
            clean_df = checker.process_stock(symbol)
            results[symbol] = clean_df
            
            # 保存清洗后的数据
            if output_dir:
                output_path = Path(output_dir) / f"{symbol}_clean.csv"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                clean_df.to_csv(output_path, index=False)
                
        except Exception as e:
            LOGGER.error(f"处理 {symbol} 失败: {e}")
    
    return results


if __name__ == "__main__":
    # 测试数据质量检查
    logging.basicConfig(level=logging.INFO)
    
    checker = DataQualityChecker(data_dir="data")
    
    # 生成质量报告
    test_symbols = ["000001", "000002", "002594"]
    
    for symbol in test_symbols:
        try:
            report = checker.generate_quality_report(symbol)
            print(f"\n{'=' * 60}")
            print(f"数据质量报告: {symbol}")
            print(f"{'=' * 60}")
            print(f"总行数: {report['total_rows']}")
            print(f"日期范围: {report['date_range']['start']} ~ {report['date_range']['end']}")
            print(f"停牌天数: {report['suspension_days']}")
            print(f"涨停天数: {report['limit_price_days']['upper_limit']}")
            print(f"跌停天数: {report['limit_price_days']['lower_limit']}")
        except Exception as e:
            print(f"处理 {symbol} 失败: {e}")

