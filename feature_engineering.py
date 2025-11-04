"""
特征工程模块
=============
统一的特征生成和标签构建流程

主要功能：
1. 批量计算所有因子（55个）
   - 自定义因子（10个）
   - Alpha101因子（30个）
   - 技术因子（10个）
   - 行业因子（5个）
2. 三重障碍法标签生成
3. 因子预处理
4. 时间序列数据切分
"""

import numpy as np
import pandas as pd
from pathlib import Path
from typing import Tuple, Optional, Dict
import warnings
warnings.filterwarnings('ignore')

# 导入因子计算模块
from factor_lib.custom_factors import (
    TrendSpreadFactor, PriceZoneFactor, KDJ_JFactor, KDJ_SpreadFactor,
    VolumeBreathRatioFactor, PriceVolumeCorrelationFactor,
    VolumePullbackFactor, VWAPRatioFactor, ATRPositionFactor, RSVFactor
)
from factor_lib.alpha101_factors import Alpha101Factors
from factor_lib.technical_factors import TechnicalFactors
from factor_lib.industry_factors import IndustryFactors
from factor_lib.preprocessing import FactorPreprocessor


class TripleBarrierLabeler:
    """三重障碍法标签生成器"""
    
    def __init__(
        self,
        profit_take: float = 0.10,    # 止盈阈值 10%
        stop_loss: float = 0.05,       # 止损阈值 5%
        time_limit: int = 10           # 时间限制 10天
    ):
        """
        初始化三重障碍法标签生成器
        
        Parameters
        ----------
        profit_take : float
            止盈阈值（比例）
        stop_loss : float
            止损阈值（比例）
        time_limit : int
            时间限制（天数）
        """
        self.profit_take = profit_take
        self.stop_loss = stop_loss
        self.time_limit = time_limit
    
    def generate_labels(self, close_prices: pd.Series) -> pd.Series:
        """
        生成三重障碍法标签
        
        Parameters
        ----------
        close_prices : pd.Series
            收盘价序列
        
        Returns
        -------
        pd.Series
            标签序列：1=买入（先触及上轨）, -1=卖出（先触及下轨）, 0=中性（超时）
        """
        labels = pd.Series(0, index=close_prices.index)
        
        for i in range(len(close_prices) - self.time_limit):
            entry_price = close_prices.iloc[i]
            
            # 未来N天的价格
            future_prices = close_prices.iloc[i+1:i+1+self.time_limit]
            
            # 计算收益率
            returns = (future_prices - entry_price) / entry_price
            
            # 找到第一次触及上轨的位置
            profit_hit = returns[returns >= self.profit_take]
            # 找到第一次触及下轨的位置
            loss_hit = returns[returns <= -self.stop_loss]
            
            if len(profit_hit) > 0 and len(loss_hit) > 0:
                # 都触及，看哪个先发生
                if profit_hit.index[0] < loss_hit.index[0]:
                    labels.iloc[i] = 1  # 先止盈
                else:
                    labels.iloc[i] = -1  # 先止损
            elif len(profit_hit) > 0:
                labels.iloc[i] = 1  # 只触及止盈
            elif len(loss_hit) > 0:
                labels.iloc[i] = -1  # 只触及止损
            else:
                labels.iloc[i] = 0  # 超时，未触及上下轨
        
        return labels
    
    def generate_continuous_labels(self, close_prices: pd.Series) -> pd.Series:
        """
        生成连续标签（未来N日收益率）
        
        Parameters
        ----------
        close_prices : pd.Series
            收盘价序列
        
        Returns
        -------
        pd.Series
            未来收益率
        """
        return close_prices.pct_change(self.time_limit).shift(-self.time_limit)


class FeatureEngineer:
    """
    特征工程管理器
    
    统一管理所有因子的计算、预处理和标签生成
    """
    
    def __init__(
        self,
        data_dir: str = "data",
        industry_mapping_file: str = "stocklist.csv",
        use_preprocessing: bool = True
    ):
        """
        初始化特征工程管理器
        
        Parameters
        ----------
        data_dir : str
            数据目录路径
        industry_mapping_file : str
            行业映射文件路径
        use_preprocessing : bool
            是否使用因子预处理
        """
        self.data_dir = Path(data_dir)
        self.industry_mapping_file = industry_mapping_file
        self.use_preprocessing = use_preprocessing
        
        # 加载行业映射
        self.industry_mapping = pd.read_csv(industry_mapping_file)
        
        # 初始化预处理器
        if use_preprocessing:
            self.preprocessor = FactorPreprocessor()
    
    def _load_stock_data(self, stock_code: str) -> pd.DataFrame:
        """加载单只股票数据"""
        for code_fmt in [stock_code, stock_code.split('.')[0]]:
            file_path = self.data_dir / f"{code_fmt}.csv"
            if file_path.exists():
                df = pd.read_csv(file_path)
                df.columns = df.columns.str.lower()
                return df.sort_values('date')
        
        raise FileNotFoundError(f"Data file not found for {stock_code}")
    
    def calculate_all_factors(self, stock_code: str) -> pd.DataFrame:
        """
        计算单只股票的所有因子（55个）
        
        Parameters
        ----------
        stock_code : str
            股票代码
        
        Returns
        -------
        pd.DataFrame
            包含所有因子的DataFrame
        """
        # 加载数据
        data = self._load_stock_data(stock_code)
        
        result = pd.DataFrame()
        result['date'] = data['date']
        result['ts_code'] = stock_code
        result['close'] = data['close']
        result['open'] = data['open']
        result['high'] = data['high']
        result['low'] = data['low']
        result['volume'] = data['volume']
        
        # 1. 自定义因子（10个）
        print(f"  计算自定义因子...")
        custom_factors = self._calculate_custom_factors(data)
        result = result.merge(custom_factors, left_index=True, right_index=True, how='left')
        
        # 2. Alpha101因子（30个）
        print(f"  计算Alpha101因子...")
        alpha101_factors = self._calculate_alpha101_factors(data)
        result = result.merge(alpha101_factors, left_index=True, right_index=True, how='left')
        
        # 3. 技术因子（10个）
        print(f"  计算技术因子...")
        tech_factors = self._calculate_technical_factors(data)
        result = result.merge(tech_factors, left_index=True, right_index=True, how='left')
        
        # 4. 行业因子（5个）
        print(f"  计算行业因子...")
        industry_factors = self._calculate_industry_factors(data, stock_code)
        result = result.merge(industry_factors, left_index=True, right_index=True, how='left')
        
        return result
    
    def _calculate_custom_factors(self, data: pd.DataFrame) -> pd.DataFrame:
        """计算自定义因子（10个）"""
        factors = pd.DataFrame(index=data.index)
        
        # 趋势强度
        trend_spread = TrendSpreadFactor()
        factors['f_trend_spread'] = trend_spread.calculate(data)
        
        # 价格位置
        price_zone = PriceZoneFactor()
        factors['f_price_zone'] = price_zone.calculate(data)
        
        # KDJ_J
        kdj_j = KDJ_JFactor()
        factors['f_kdj_j'] = kdj_j.calculate(data)
        
        # KDJ K-D价差
        kdj_spread = KDJ_SpreadFactor()
        factors['f_kdj_spread'] = kdj_spread.calculate(data)
        
        # 成交量呼吸度
        vol_breath = VolumeBreathRatioFactor()
        factors['f_volume_breath'] = vol_breath.calculate(data)
        
        # 量价相关性
        pv_corr = PriceVolumeCorrelationFactor()
        factors['f_pv_corr'] = pv_corr.calculate(data)
        
        # 缩量回调
        vol_pullback = VolumePullbackFactor()
        factors['f_vol_pullback'] = vol_pullback.calculate(data)
        
        # VWAP比率
        vwap_ratio = VWAPRatioFactor()
        factors['f_vwap_ratio'] = vwap_ratio.calculate(data)
        
        # ATR位置
        atr_pos = ATRPositionFactor()
        factors['f_atr_position'] = atr_pos.calculate(data)
        
        # RSV
        rsv = RSVFactor()
        factors['f_rsv'] = rsv.calculate(data)
        
        return factors
    
    def _calculate_alpha101_factors(self, data: pd.DataFrame) -> pd.DataFrame:
        """计算Alpha101因子（30个）"""
        alpha = Alpha101Factors(data)
        factors = alpha.calculate_all()
        
        # 只保留因子列
        factor_cols = [col for col in factors.columns if col.startswith('alpha_')]
        return factors[factor_cols]
    
    def _calculate_technical_factors(self, data: pd.DataFrame) -> pd.DataFrame:
        """计算技术因子（10个）"""
        tech = TechnicalFactors(data)
        factors = tech.calculate_all()
        
        # 只保留因子列
        factor_cols = [col for col in factors.columns if col not in ['date', 'ts_code']]
        return factors[factor_cols]
    
    def _calculate_industry_factors(self, data: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        """计算行业因子（5个）"""
        industry = IndustryFactors(data, self.industry_mapping, stock_code)
        factors = industry.calculate_all()
        
        # 只保留因子列
        factor_cols = [col for col in factors.columns if col not in ['date', 'ts_code', 'industry']]
        return factors[factor_cols]
    
    def generate_labels(
        self,
        data: pd.DataFrame,
        label_type: str = 'triple_barrier',
        **kwargs
    ) -> pd.Series:
        """
        生成标签
        
        Parameters
        ----------
        data : pd.DataFrame
            包含收盘价的数据
        label_type : str
            标签类型：'triple_barrier', 'continuous'
        **kwargs
            三重障碍法的参数
        
        Returns
        -------
        pd.Series
            标签序列
        """
        close_prices = data['close']
        
        labeler = TripleBarrierLabeler(**kwargs)
        
        if label_type == 'triple_barrier':
            return labeler.generate_labels(close_prices)
        elif label_type == 'continuous':
            return labeler.generate_continuous_labels(close_prices)
        else:
            raise ValueError(f"Unknown label type: {label_type}")
    
    def build_dataset(
        self,
        stock_code: str,
        label_type: str = 'triple_barrier',
        label_params: Optional[Dict] = None,
        dropna: bool = True
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """
        构建完整的特征+标签数据集
        
        Parameters
        ----------
        stock_code : str
            股票代码
        label_type : str
            标签类型
        label_params : dict, optional
            标签参数
        dropna : bool
            是否删除缺失值
        
        Returns
        -------
        Tuple[pd.DataFrame, pd.Series]
            (特征DataFrame, 标签Series)
        """
        print(f"构建 {stock_code} 的特征数据集...")
        
        # 计算所有因子
        features = self.calculate_all_factors(stock_code)
        
        # 生成标签
        print(f"  生成标签...")
        label_params = label_params or {}
        labels = self.generate_labels(features, label_type, **label_params)
        features['label'] = labels
        
        # 删除缺失值
        if dropna:
            features = features.dropna()
        
        # 分离特征和标签
        label_col = features['label']
        
        # 保留元数据列
        meta_cols = ['date', 'ts_code', 'close', 'open', 'high', 'low', 'volume']
        
        # 因子列
        factor_cols = [col for col in features.columns 
                      if col not in meta_cols + ['label']]
        
        X = features[factor_cols]
        y = label_col
        
        # 预处理因子
        if self.use_preprocessing:
            print(f"  预处理因子...")
            X = pd.DataFrame(
                self.preprocessor.fit_transform(X.values),
                columns=X.columns,
                index=X.index
            )
        
        print(f"  完成！特征数: {X.shape[1]}, 样本数: {X.shape[0]}")
        
        return X, y
    
    def build_multi_stock_dataset(
        self,
        stock_list: list,
        label_type: str = 'triple_barrier',
        label_params: Optional[Dict] = None,
        dropna: bool = True,
        save_path: Optional[str] = None
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """
        构建多股票的特征数据集
        
        Parameters
        ----------
        stock_list : list
            股票代码列表
        label_type : str
            标签类型
        label_params : dict, optional
            标签参数
        dropna : bool
            是否删除缺失值
        save_path : str, optional
            保存路径
        
        Returns
        -------
        Tuple[pd.DataFrame, pd.Series]
            (特征DataFrame, 标签Series)
        """
        print(f"构建多股票特征数据集 ({len(stock_list)} 只股票)...")
        
        all_X = []
        all_y = []
        
        for i, stock_code in enumerate(stock_list, 1):
            print(f"\n[{i}/{len(stock_list)}] {stock_code}")
            try:
                X, y = self.build_dataset(
                    stock_code,
                    label_type,
                    label_params,
                    dropna
                )
                all_X.append(X)
                all_y.append(y)
            except Exception as e:
                print(f"  错误: {e}")
                continue
        
        if not all_X:
            raise ValueError("No valid data found for any stock")
        
        # 合并所有数据
        print(f"\n合并所有数据...")
        X_combined = pd.concat(all_X, ignore_index=True)
        y_combined = pd.concat(all_y, ignore_index=True)
        
        # 保存
        if save_path:
            print(f"保存到 {save_path}...")
            save_path = Path(save_path)
            save_path.mkdir(parents=True, exist_ok=True)
            
            X_combined.to_csv(save_path / 'features.csv', index=False)
            y_combined.to_csv(save_path / 'labels.csv', index=False)
        
        print(f"\n完成！总特征数: {X_combined.shape[1]}, 总样本数: {X_combined.shape[0]}")
        print(f"标签分布:")
        print(y_combined.value_counts())
        
        return X_combined, y_combined


def time_series_split(
    X: pd.DataFrame,
    y: pd.Series,
    n_splits: int = 5,
    test_size: float = 0.2
) -> list:
    """
    时间序列交叉验证切分
    
    Parameters
    ----------
    X : pd.DataFrame
        特征
    y : pd.Series
        标签
    n_splits : int
        切分数量
    test_size : float
        测试集比例
    
    Returns
    -------
    list
        [(train_idx, test_idx), ...]
    """
    n_samples = len(X)
    test_samples = int(n_samples * test_size)
    
    splits = []
    
    for i in range(n_splits):
        # 滚动窗口切分
        test_end = n_samples - i * test_samples
        test_start = test_end - test_samples
        train_end = test_start
        
        if train_end <= test_samples:
            break
        
        train_idx = list(range(0, train_end))
        test_idx = list(range(test_start, test_end))
        
        splits.append((train_idx, test_idx))
    
    return splits[::-1]  # 从早到晚


if __name__ == "__main__":
    # 测试代码
    import sys
    
    if len(sys.argv) > 1:
        stock_code = sys.argv[1]
        
        # 初始化特征工程器
        engineer = FeatureEngineer(
            data_dir="data",
            industry_mapping_file="stocklist.csv",
            use_preprocessing=True
        )
        
        # 构建数据集
        X, y = engineer.build_dataset(
            stock_code=stock_code,
            label_type='triple_barrier',
            label_params={
                'profit_take': 0.10,
                'stop_loss': 0.05,
                'time_limit': 10
            },
            dropna=True
        )
        
        print(f"\n=== 数据集统计 ===")
        print(f"特征维度: {X.shape}")
        print(f"标签维度: {y.shape}")
        print(f"\n标签分布:")
        print(y.value_counts())
        print(f"\n特征前5行:")
        print(X.head())
        
    else:
        print("用法: python feature_engineering.py <stock_code>")
        print("示例: python feature_engineering.py 000001")

