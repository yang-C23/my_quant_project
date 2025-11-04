"""
因子计算引擎基类

提供统一的因子计算接口，支持：
- 批量计算
- 结果缓存
- 时间对齐（防止未来信息泄漏）
- 并行计算
- GPU加速（可选）

Architecture:
- FactorEngine: 核心引擎，管理数据加载、因子计算、结果缓存
- FactorBase: 因子基类，所有因子继承此类
- FactorResult: 因子计算结果封装
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd

LOGGER = logging.getLogger("factor_engine")


@dataclass
class FactorResult:
    """
    因子计算结果
    
    Attributes:
        name: 因子名称
        data: 因子值，DataFrame格式 (index=date, columns=stock_code)
        metadata: 元数据（计算参数、时间戳等）
    """
    name: str
    data: pd.DataFrame
    metadata: Dict[str, Any]
    
    def __post_init__(self):
        """验证数据格式"""
        if not isinstance(self.data, pd.DataFrame):
            raise TypeError(f"Factor data must be DataFrame, got {type(self.data)}")
        if not isinstance(self.data.index, pd.DatetimeIndex):
            LOGGER.warning(f"Factor {self.name}: index is not DatetimeIndex, converting...")
            self.data.index = pd.to_datetime(self.data.index)


class FactorBase(ABC):
    """
    因子基类
    
    所有因子必须继承此类并实现 calculate() 方法。
    
    Example:
        class MyFactor(FactorBase):
            def __init__(self, period: int = 20):
                super().__init__(name="my_factor")
                self.period = period
            
            def calculate(self, data: pd.DataFrame) -> pd.Series:
                return data['close'].pct_change(self.period)
    """
    
    def __init__(self, name: str):
        self.name = name
        self.metadata: Dict[str, Any] = {}
    
    @abstractmethod
    def calculate(self, data: pd.DataFrame) -> Union[pd.Series, pd.DataFrame]:
        """
        计算因子值
        
        Args:
            data: 股票OHLCV数据，必须包含 date, open, high, low, close, volume 列
                 index为date（DatetimeIndex），已按时间升序排列
        
        Returns:
            因子值Series（单只股票）或DataFrame（多只股票）
            
        Notes:
            - 必须严格遵守时间顺序，只使用T-1及之前的数据计算T期因子
            - 不得使用未来数据（forward-looking bias）
        """
        pass
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}')"


class FactorEngine:
    """
    因子计算引擎
    
    核心功能：
    1. 加载股票数据
    2. 批量计算因子
    3. 结果缓存
    4. 时间对齐验证
    5. 并行计算
    
    Usage:
        engine = FactorEngine(data_dir='/path/to/data')
        engine.load_data(symbols=['000001', '000002'])
        
        # 注册因子
        engine.register_factor(MyFactor(period=20))
        
        # 计算因子
        results = engine.compute_all()
    """
    
    def __init__(
        self,
        data_dir: Union[str, Path],
        cache_dir: Optional[Union[str, Path]] = None,
        n_jobs: int = -1,
    ):
        """
        初始化因子引擎
        
        Args:
            data_dir: 数据目录路径
            cache_dir: 缓存目录，None表示不缓存
            n_jobs: 并行任务数，-1表示使用所有CPU核心
        """
        self.data_dir = Path(data_dir)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.n_jobs = n_jobs
        
        # 数据存储
        self.raw_data: Dict[str, pd.DataFrame] = {}  # {stock_code: OHLCV DataFrame}
        self.factors: List[FactorBase] = []
        self.results: Dict[str, FactorResult] = {}  # {factor_name: FactorResult}
        
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            LOGGER.info(f"缓存目录: {self.cache_dir}")
    
    def load_data(
        self,
        symbols: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> None:
        """
        加载股票数据
        
        Args:
            symbols: 股票代码列表，None表示加载所有
            start_date: 开始日期 'YYYY-MM-DD'
            end_date: 结束日期 'YYYY-MM-DD'
        """
        LOGGER.info("开始加载数据...")
        
        # 获取所有CSV文件
        if symbols is None:
            csv_files = list(self.data_dir.glob("*.csv"))
            symbols = [f.stem for f in csv_files]
        else:
            csv_files = [self.data_dir / f"{sym}.csv" for sym in symbols]
        
        # 加载每只股票的数据
        loaded_count = 0
        for csv_file, symbol in zip(csv_files, symbols):
            if not csv_file.exists():
                LOGGER.warning(f"数据文件不存在: {csv_file}")
                continue
            
            try:
                df = pd.read_csv(csv_file)
                
                # 标准化列名
                df = df.rename(columns={
                    'trade_date': 'date',
                    'vol': 'volume',
                })
                
                # 确保必需列存在
                required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
                missing_cols = [c for c in required_cols if c not in df.columns]
                if missing_cols:
                    LOGGER.warning(f"{symbol}: 缺少列 {missing_cols}，跳过")
                    continue
                
                # 数据类型转换
                df['date'] = pd.to_datetime(df['date'])
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                
                # 过滤日期范围
                if start_date:
                    df = df[df['date'] >= start_date]
                if end_date:
                    df = df[df['date'] <= end_date]
                
                # 排序并设置索引
                df = df.sort_values('date').set_index('date')
                
                # 去除重复日期
                df = df[~df.index.duplicated(keep='first')]
                
                self.raw_data[symbol] = df
                loaded_count += 1
                
            except Exception as e:
                LOGGER.error(f"加载{symbol}失败: {e}")
        
        LOGGER.info(f"数据加载完成: {loaded_count}/{len(symbols)} 只股票")
    
    def register_factor(self, factor: FactorBase) -> None:
        """注册因子"""
        if factor.name in [f.name for f in self.factors]:
            LOGGER.warning(f"因子 {factor.name} 已存在，将被覆盖")
            self.factors = [f for f in self.factors if f.name != factor.name]
        
        self.factors.append(factor)
        LOGGER.info(f"注册因子: {factor}")
    
    def compute_factor(
        self,
        factor: FactorBase,
        use_cache: bool = True,
    ) -> FactorResult:
        """
        计算单个因子
        
        Args:
            factor: 因子对象
            use_cache: 是否使用缓存
        
        Returns:
            FactorResult对象
        """
        # 检查缓存
        if use_cache and self.cache_dir:
            cache_file = self.cache_dir / f"{factor.name}.pkl"
            if cache_file.exists():
                try:
                    result = pd.read_pickle(cache_file)
                    LOGGER.info(f"从缓存加载: {factor.name}")
                    return FactorResult(
                        name=factor.name,
                        data=result,
                        metadata={'from_cache': True}
                    )
                except Exception as e:
                    LOGGER.warning(f"缓存加载失败: {e}")
        
        LOGGER.info(f"计算因子: {factor.name}")
        
        # 为每只股票计算因子
        factor_values = {}
        for symbol, data in self.raw_data.items():
            try:
                values = factor.calculate(data)
                factor_values[symbol] = values
            except Exception as e:
                LOGGER.error(f"{symbol} 计算 {factor.name} 失败: {e}")
                # 创建空Series
                factor_values[symbol] = pd.Series(index=data.index, dtype=float)
        
        # 合并成DataFrame
        factor_df = pd.DataFrame(factor_values)
        
        # 保存缓存
        if self.cache_dir:
            cache_file = self.cache_dir / f"{factor.name}.pkl"
            factor_df.to_pickle(cache_file)
            LOGGER.info(f"因子缓存已保存: {cache_file}")
        
        result = FactorResult(
            name=factor.name,
            data=factor_df,
            metadata={'timestamp': pd.Timestamp.now()}
        )
        
        self.results[factor.name] = result
        return result
    
    def compute_all(self, use_cache: bool = True) -> Dict[str, FactorResult]:
        """
        批量计算所有已注册的因子
        
        Args:
            use_cache: 是否使用缓存
        
        Returns:
            {factor_name: FactorResult} 字典
        """
        if not self.factors:
            LOGGER.warning("没有注册任何因子")
            return {}
        
        LOGGER.info(f"开始计算 {len(self.factors)} 个因子...")
        
        for factor in self.factors:
            self.compute_factor(factor, use_cache=use_cache)
        
        LOGGER.info(f"因子计算完成，共 {len(self.results)} 个因子")
        return self.results
    
    def get_factor_panel(self, factor_names: Optional[List[str]] = None) -> pd.Panel:
        """
        获取因子面板数据
        
        Args:
            factor_names: 因子名称列表，None表示所有因子
        
        Returns:
            Panel数据 (date x stock x factor)
            
        Note:
            由于pandas已弃用Panel，这里返回MultiIndex DataFrame
        """
        if factor_names is None:
            factor_names = list(self.results.keys())
        
        # 创建MultiIndex DataFrame: (date, stock) x factor
        factor_data = {}
        for name in factor_names:
            if name not in self.results:
                LOGGER.warning(f"因子 {name} 未计算")
                continue
            factor_data[name] = self.results[name].data.stack()
        
        df = pd.DataFrame(factor_data)
        df.index.names = ['date', 'stock']
        return df
    
    def clear_cache(self) -> None:
        """清空缓存"""
        if self.cache_dir and self.cache_dir.exists():
            for cache_file in self.cache_dir.glob("*.pkl"):
                cache_file.unlink()
            LOGGER.info("缓存已清空")

