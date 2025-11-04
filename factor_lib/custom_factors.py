"""
策略衍生因子库

基于通达信策略逻辑衍生的因子，用于机器学习模型训练。

这些因子直接反映了策略的核心逻辑：
- 趋势强度
- 价格位置
- KDJ动量
- 量价关系
- 技术指标

所有因子严格遵守时间顺序，不使用未来信息。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .base import FactorBase


class TrendSpreadFactor(FactorBase):
    """
    趋势价差因子
    
    计算短期趋势线（白线）与长期多空线（黄线）的相对价差。
    
    Formula: (EMA(EMA(C,N1),N1) - MA4) / MA4
    where MA4 = (MA(C,M1) + MA(C,M2) + MA(C,M3) + MA(C,M4)) / 4
    """
    
    def __init__(
        self,
        short_period: int = 10,
        ma_periods: tuple = (14, 28, 57, 114),
    ):
        super().__init__(name=f"F_Trend_Spread_{short_period}")
        self.short_period = short_period
        self.ma_periods = ma_periods
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        close = data['close']
        
        # 白线：双重EMA
        ema1 = close.ewm(span=self.short_period, adjust=False).mean()
        white_line = ema1.ewm(span=self.short_period, adjust=False).mean()
        
        # 黄线：四均线平均
        ma1 = close.rolling(self.ma_periods[0]).mean()
        ma2 = close.rolling(self.ma_periods[1]).mean()
        ma3 = close.rolling(self.ma_periods[2]).mean()
        ma4 = close.rolling(self.ma_periods[3]).mean()
        yellow_line = (ma1 + ma2 + ma3 + ma4) / 4.0
        
        # 相对价差
        return (white_line - yellow_line) / (yellow_line + 1e-10)


class PriceZoneFactor(FactorBase):
    """
    价格区间位置因子
    
    衡量收盘价在白线和黄线之间的相对位置。
    
    Formula: (Close - 黄线) / (白线 - 黄线)
    
    Values:
        0: 在黄线上
        0.5: 在中间
        1: 在白线上
        >1: 突破白线（强势）
        <0: 跌破黄线（弱势）
    """
    
    def __init__(
        self,
        short_period: int = 10,
        ma_periods: tuple = (14, 28, 57, 114),
    ):
        super().__init__(name=f"F_Price_Zone_{short_period}")
        self.short_period = short_period
        self.ma_periods = ma_periods
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        close = data['close']
        
        # 白线
        ema1 = close.ewm(span=self.short_period, adjust=False).mean()
        white_line = ema1.ewm(span=self.short_period, adjust=False).mean()
        
        # 黄线
        ma1 = close.rolling(self.ma_periods[0]).mean()
        ma2 = close.rolling(self.ma_periods[1]).mean()
        ma3 = close.rolling(self.ma_periods[2]).mean()
        ma4 = close.rolling(self.ma_periods[3]).mean()
        yellow_line = (ma1 + ma2 + ma3 + ma4) / 4.0
        
        # 相对位置
        denominator = white_line - yellow_line
        return (close - yellow_line) / (denominator + 1e-10)


class KDJFactors(FactorBase):
    """
    KDJ指标因子组
    
    包含K、D、J三个值，用于捕捉超买超卖状态。
    
    Returns:
        DataFrame with columns: K, D, J
    """
    
    def __init__(self, period: int = 9, k_period: int = 3, d_period: int = 3):
        super().__init__(name=f"F_KDJ_{period}")
        self.period = period
        self.k_period = k_period
        self.d_period = d_period
    
    def calculate(self, data: pd.DataFrame) -> pd.DataFrame:
        high = data['high']
        low = data['low']
        close = data['close']
        
        # RSV
        lowest_low = low.rolling(self.period).min()
        highest_high = high.rolling(self.period).max()
        rsv = (close - lowest_low) / (highest_high - lowest_low + 1e-10) * 100.0
        
        # K值：RSV的EMA
        k = rsv.ewm(span=self.k_period, adjust=False).mean()
        
        # D值：K的EMA
        d = k.ewm(span=self.d_period, adjust=False).mean()
        
        # J值
        j = 3.0 * k - 2.0 * d
        
        result = pd.DataFrame({
            f'F_KDJ_K_{self.period}': k,
            f'F_KDJ_D_{self.period}': d,
            f'F_KDJ_J_{self.period}': j,
        }, index=data.index)
        
        return result


class KDJ_JFactor(FactorBase):
    """
    KDJ的J值因子
    
    J值是KDJ指标中最敏感的指标，用于捕捉超买超卖。
    J < 10 或 J < 0 表示超卖，J > 90 或 J > 100 表示超买。
    """
    
    def __init__(self, period: int = 9, k_period: int = 3, d_period: int = 3):
        super().__init__(name=f"F_KDJ_J_{period}")
        self.period = period
        self.k_period = k_period
        self.d_period = d_period
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        high = data['high']
        low = data['low']
        close = data['close']
        
        # RSV
        lowest_low = low.rolling(self.period).min()
        highest_high = high.rolling(self.period).max()
        rsv = (close - lowest_low) / (highest_high - lowest_low + 1e-10) * 100.0
        
        # K值
        k = rsv.ewm(span=self.k_period, adjust=False).mean()
        
        # D值
        d = k.ewm(span=self.d_period, adjust=False).mean()
        
        # J值
        j = 3.0 * k - 2.0 * d
        
        return j


class KDJ_SpreadFactor(FactorBase):
    """
    KDJ的K-D价差因子
    
    K-D价差反映动量的变化方向和强度。
    正值表示上涨动量，负值表示下跌动量。
    """
    
    def __init__(self, period: int = 9, k_period: int = 3, d_period: int = 3):
        super().__init__(name=f"F_KDJ_Spread_{period}")
        self.period = period
        self.k_period = k_period
        self.d_period = d_period
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        high = data['high']
        low = data['low']
        close = data['close']
        
        # RSV
        lowest_low = low.rolling(self.period).min()
        highest_high = high.rolling(self.period).max()
        rsv = (close - lowest_low) / (highest_high - lowest_low + 1e-10) * 100.0
        
        # K值
        k = rsv.ewm(span=self.k_period, adjust=False).mean()
        
        # D值
        d = k.ewm(span=self.d_period, adjust=False).mean()
        
        # K-D价差
        return k - d


class VolumeBreathRatioFactor(FactorBase):
    """
    成交量呼吸度比率因子
    
    衡量成交量的高低波动程度（放量缩量交替的幅度）。
    
    Formula: AVGHIGH / AVGLOW
    where:
        AVGHIGH = mean(top 3 volumes in N days)
        AVGLOW = mean(bottom 3 volumes in N days)
    """
    
    def __init__(self, period: int = 30):
        super().__init__(name=f"F_Volume_Breath_{period}")
        self.period = period
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        volume = data['volume']
        
        def calc_breath(vol_window):
            if len(vol_window) < 3:
                return np.nan
            sorted_vol = sorted(vol_window)
            avghigh = np.mean(sorted_vol[-3:])
            avglow = np.mean(sorted_vol[:3])
            return avghigh / (avglow + 1e-10) if avglow > 0 else np.nan
        
        return volume.rolling(self.period).apply(calc_breath, raw=True)


class PriceVolumeCorrelationFactor(FactorBase):
    """
    量价相关性因子
    
    计算价格变动率与成交量变动率的相关系数。
    
    正相关：量价同步
    负相关：量价背离
    """
    
    def __init__(self, period: int = 20):
        super().__init__(name=f"F_PV_Corr_{period}")
        self.period = period
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        price_returns = data['close'].pct_change()
        volume_returns = data['volume'].pct_change()
        
        return price_returns.rolling(self.period).corr(volume_returns)


class VolumePullbackFactor(FactorBase):
    """
    缩量回调因子
    
    当前成交量相对于N日平均成交量的比率。
    
    <0.7: 明显缩量
    0.7-1.3: 正常
    >1.3: 放量
    """
    
    def __init__(self, period: int = 20):
        super().__init__(name=f"F_Vol_Pullback_{period}")
        self.period = period
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        volume = data['volume']
        avg_volume = volume.rolling(self.period).mean()
        return volume / (avg_volume + 1e-10)


class VWAPRatioFactor(FactorBase):
    """
    VWAP比率因子
    
    收盘价相对于成交量加权平均价格的比率。
    
    >1: 价格高于平均成本（多数人盈利）
    <1: 价格低于平均成本（多数人亏损）
    """
    
    def __init__(self, period: int = 20):
        super().__init__(name=f"F_VWAP_Ratio_{period}")
        self.period = period
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        typical_price = (data['high'] + data['low'] + data['close']) / 3.0
        pv = typical_price * data['volume']
        
        vwap = pv.rolling(self.period).sum() / (data['volume'].rolling(self.period).sum() + 1e-10)
        
        return data['close'] / (vwap + 1e-10)


class ATRPositionFactor(FactorBase):
    """
    ATR止损空间因子
    
    衡量当前价格距离20日低点的距离（以ATR为单位）。
    
    Formula: (Close - LLV(Low, 20)) / ATR
    
    高值：价格远离低点，止损空间大
    低值：价格接近低点，风险高
    """
    
    def __init__(self, atr_period: int = 14, lookback: int = 20):
        super().__init__(name=f"F_ATR_Position_{atr_period}")
        self.atr_period = atr_period
        self.lookback = lookback
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        high = data['high']
        low = data['low']
        close = data['close']
        
        # True Range
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # ATR
        atr = tr.rolling(self.atr_period).mean()
        
        # N日低点
        lowest_low = low.rolling(self.lookback).min()
        
        # 止损空间（以ATR为单位）
        return (close - lowest_low) / (atr + 1e-10)


class RSVFactor(FactorBase):
    """
    原始RSV因子（未平滑）
    
    衡量收盘价在N日内的相对位置。
    
    Formula: (Close - LLV(Low, N)) / (HHV(High, N) - LLV(Low, N)) * 100
    """
    
    def __init__(self, period: int = 9):
        super().__init__(name=f"F_RSV_{period}")
        self.period = period
    
    def calculate(self, data: pd.DataFrame) -> pd.Series:
        high = data['high']
        low = data['low']
        close = data['close']
        
        lowest_low = low.rolling(self.period).min()
        highest_high = high.rolling(self.period).max()
        
        return (close - lowest_low) / (highest_high - lowest_low + 1e-10) * 100.0
