"""
经典技术指标因子库
====================
实现10个经典技术分析因子

包括：
1. 动量类（3个）: ROC, Momentum, Price Acceleration
2. 波动率类（2个）: ATR, Bollinger Bands Width
3. 趋势类（3个）: MACD, ADX, Aroon
4. 超买超卖类（2个）: RSI, Stochastic
"""

import numpy as np
import pandas as pd
from typing import Tuple


class TechnicalFactors:
    """经典技术指标因子"""
    
    def __init__(self, data: pd.DataFrame):
        """
        初始化技术因子计算器
        
        Parameters
        ----------
        data : pd.DataFrame
            包含列：['date', 'open', 'high', 'low', 'close', 'volume']
        """
        self.data = data.copy()
        
        # 确保数据按日期排序
        if 'date' in self.data.columns:
            self.data = self.data.sort_values('date')
        
        # 提取基础列
        self.open = self.data['open']
        self.high = self.data['high']
        self.low = self.data['low']
        self.close = self.data['close']
        self.volume = self.data['volume']
    
    # ============================================================
    # 动量类因子（3个）
    # ============================================================
    
    def roc(self, period: int = 12) -> pd.Series:
        """
        Rate of Change (变化率)
        
        ROC = (Close - Close[n]) / Close[n] * 100
        
        Parameters
        ----------
        period : int, default=12
            回溯周期
        
        Returns
        -------
        pd.Series
            ROC值
        """
        return (self.close - self.close.shift(period)) / (self.close.shift(period) + 1e-8) * 100
    
    def momentum(self, period: int = 10) -> pd.Series:
        """
        Momentum (动量)
        
        MOM = Close - Close[n]
        
        Parameters
        ----------
        period : int, default=10
            回溯周期
        
        Returns
        -------
        pd.Series
            动量值
        """
        return self.close - self.close.shift(period)
    
    def price_acceleration(self, period: int = 5) -> pd.Series:
        """
        Price Acceleration (价格加速度)
        
        加速度 = ROC[1] - ROC[1][n]
        
        Parameters
        ----------
        period : int, default=5
            回溯周期
        
        Returns
        -------
        pd.Series
            价格加速度
        """
        roc_1 = self.roc(1)
        return roc_1 - roc_1.shift(period)
    
    # ============================================================
    # 波动率类因子（2个）
    # ============================================================
    
    def atr(self, period: int = 14) -> pd.Series:
        """
        Average True Range (平均真实波幅)
        
        TR = max(high - low, abs(high - close[1]), abs(low - close[1]))
        ATR = EMA(TR, period)
        
        Parameters
        ----------
        period : int, default=14
            计算周期
        
        Returns
        -------
        pd.Series
            ATR值
        """
        high_low = self.high - self.low
        high_close = np.abs(self.high - self.close.shift(1))
        low_close = np.abs(self.low - self.close.shift(1))
        
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.ewm(span=period, adjust=False, min_periods=period).mean()
        
        return atr
    
    def bollinger_width(self, period: int = 20, num_std: float = 2.0) -> pd.Series:
        """
        Bollinger Bands Width (布林带宽度)
        
        BB_Width = (Upper_Band - Lower_Band) / Middle_Band
        Upper_Band = MA(Close, period) + num_std * STD(Close, period)
        Lower_Band = MA(Close, period) - num_std * STD(Close, period)
        
        Parameters
        ----------
        period : int, default=20
            计算周期
        num_std : float, default=2.0
            标准差倍数
        
        Returns
        -------
        pd.Series
            布林带宽度
        """
        ma = self.close.rolling(window=period, min_periods=period).mean()
        std = self.close.rolling(window=period, min_periods=period).std()
        
        upper_band = ma + num_std * std
        lower_band = ma - num_std * std
        
        bb_width = (upper_band - lower_band) / (ma + 1e-8)
        
        return bb_width
    
    # ============================================================
    # 趋势类因子（3个）
    # ============================================================
    
    def macd(self, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        MACD (Moving Average Convergence Divergence)
        
        MACD = EMA(Close, fast) - EMA(Close, slow)
        Signal = EMA(MACD, signal)
        Histogram = MACD - Signal
        
        Parameters
        ----------
        fast : int, default=12
            快速EMA周期
        slow : int, default=26
            慢速EMA周期
        signal : int, default=9
            信号线周期
        
        Returns
        -------
        Tuple[pd.Series, pd.Series, pd.Series]
            (MACD线, 信号线, 柱状图)
        """
        ema_fast = self.close.ewm(span=fast, adjust=False, min_periods=fast).mean()
        ema_slow = self.close.ewm(span=slow, adjust=False, min_periods=slow).mean()
        
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    def adx(self, period: int = 14) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Average Directional Index (平均趋向指标)
        
        计算+DI、-DI和ADX，衡量趋势强度
        
        Parameters
        ----------
        period : int, default=14
            计算周期
        
        Returns
        -------
        Tuple[pd.Series, pd.Series, pd.Series]
            (+DI, -DI, ADX)
        """
        # 计算+DM和-DM
        high_diff = self.high - self.high.shift(1)
        low_diff = self.low.shift(1) - self.low
        
        plus_dm = pd.Series(0.0, index=self.high.index)
        minus_dm = pd.Series(0.0, index=self.high.index)
        
        plus_dm[(high_diff > low_diff) & (high_diff > 0)] = high_diff[(high_diff > low_diff) & (high_diff > 0)]
        minus_dm[(low_diff > high_diff) & (low_diff > 0)] = low_diff[(low_diff > high_diff) & (low_diff > 0)]
        
        # 计算ATR
        atr = self.atr(period)
        
        # 平滑+DM和-DM
        plus_dm_smooth = plus_dm.ewm(span=period, adjust=False, min_periods=period).mean()
        minus_dm_smooth = minus_dm.ewm(span=period, adjust=False, min_periods=period).mean()
        
        # 计算+DI和-DI
        plus_di = 100 * plus_dm_smooth / (atr + 1e-8)
        minus_di = 100 * minus_dm_smooth / (atr + 1e-8)
        
        # 计算DX和ADX
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-8)
        adx = dx.ewm(span=period, adjust=False, min_periods=period).mean()
        
        return plus_di, minus_di, adx
    
    def aroon(self, period: int = 25) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Aroon Indicator (阿隆指标)
        
        Aroon Up = ((period - 最高价距今天数) / period) * 100
        Aroon Down = ((period - 最低价距今天数) / period) * 100
        Aroon Oscillator = Aroon Up - Aroon Down
        
        Parameters
        ----------
        period : int, default=25
            计算周期
        
        Returns
        -------
        Tuple[pd.Series, pd.Series, pd.Series]
            (Aroon Up, Aroon Down, Aroon Oscillator)
        """
        def days_since_high(x):
            if len(x) < period:
                return np.nan
            return period - x.argmax() - 1
        
        def days_since_low(x):
            if len(x) < period:
                return np.nan
            return period - x.argmin() - 1
        
        days_high = self.high.rolling(window=period, min_periods=period).apply(days_since_high, raw=False)
        days_low = self.low.rolling(window=period, min_periods=period).apply(days_since_low, raw=False)
        
        aroon_up = ((period - days_high) / period) * 100
        aroon_down = ((period - days_low) / period) * 100
        aroon_osc = aroon_up - aroon_down
        
        return aroon_up, aroon_down, aroon_osc
    
    # ============================================================
    # 超买超卖类因子（2个）
    # ============================================================
    
    def rsi(self, period: int = 14) -> pd.Series:
        """
        Relative Strength Index (相对强弱指标)
        
        RSI = 100 - (100 / (1 + RS))
        RS = Average Gain / Average Loss
        
        Parameters
        ----------
        period : int, default=14
            计算周期
        
        Returns
        -------
        pd.Series
            RSI值 (0-100)
        """
        delta = self.close.diff(1)
        
        gain = delta.copy()
        loss = delta.copy()
        
        gain[gain < 0] = 0
        loss[loss > 0] = 0
        loss = np.abs(loss)
        
        # 使用EMA平滑
        avg_gain = gain.ewm(span=period, adjust=False, min_periods=period).mean()
        avg_loss = loss.ewm(span=period, adjust=False, min_periods=period).mean()
        
        rs = avg_gain / (avg_loss + 1e-8)
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def stochastic(self, k_period: int = 14, d_period: int = 3, smooth: int = 3) -> Tuple[pd.Series, pd.Series]:
        """
        Stochastic Oscillator (随机指标)
        
        %K = (Close - Lowest Low) / (Highest High - Lowest Low) * 100
        %D = SMA(%K, d_period)
        
        Parameters
        ----------
        k_period : int, default=14
            K线周期
        d_period : int, default=3
            D线周期
        smooth : int, default=3
            K线平滑周期
        
        Returns
        -------
        Tuple[pd.Series, pd.Series]
            (%K, %D)
        """
        lowest_low = self.low.rolling(window=k_period, min_periods=k_period).min()
        highest_high = self.high.rolling(window=k_period, min_periods=k_period).max()
        
        # 快速K线
        fast_k = 100 * (self.close - lowest_low) / (highest_high - lowest_low + 1e-8)
        
        # 慢速K线（快速K线的SMA）
        slow_k = fast_k.rolling(window=smooth, min_periods=smooth).mean()
        
        # D线（慢速K线的SMA）
        slow_d = slow_k.rolling(window=d_period, min_periods=d_period).mean()
        
        return slow_k, slow_d
    
    # ============================================================
    # 批量计算接口
    # ============================================================
    
    def calculate_all(self) -> pd.DataFrame:
        """
        计算所有10个技术因子
        
        Returns
        -------
        pd.DataFrame
            包含所有技术因子的DataFrame
        """
        result = pd.DataFrame(index=self.data.index)
        
        # 动量类（3个）
        result['roc_12'] = self.roc(12)
        result['momentum_10'] = self.momentum(10)
        result['price_accel_5'] = self.price_acceleration(5)
        
        # 波动率类（2个）
        result['atr_14'] = self.atr(14)
        result['bb_width_20'] = self.bollinger_width(20)
        
        # 趋势类（3个）
        macd_line, signal_line, histogram = self.macd()
        result['macd'] = macd_line
        result['macd_signal'] = signal_line
        result['macd_hist'] = histogram
        
        plus_di, minus_di, adx_val = self.adx(14)
        result['adx_14'] = adx_val
        result['plus_di_14'] = plus_di
        result['minus_di_14'] = minus_di
        
        aroon_up, aroon_down, aroon_osc = self.aroon(25)
        result['aroon_up_25'] = aroon_up
        result['aroon_down_25'] = aroon_down
        result['aroon_osc_25'] = aroon_osc
        
        # 超买超卖类（2个）
        result['rsi_14'] = self.rsi(14)
        
        stoch_k, stoch_d = self.stochastic(14, 3, 3)
        result['stoch_k_14'] = stoch_k
        result['stoch_d_14'] = stoch_d
        
        # 添加日期和代码列（如果存在）
        if 'date' in self.data.columns:
            result['date'] = self.data['date'].values
        if 'ts_code' in self.data.columns:
            result['ts_code'] = self.data['ts_code'].values
        
        return result


def calculate_technical_factors(csv_file: str) -> pd.DataFrame:
    """
    为单只股票计算技术因子
    
    Parameters
    ----------
    csv_file : str
        股票数据CSV文件路径
    
    Returns
    -------
    pd.DataFrame
        包含技术因子的DataFrame
    """
    # 读取数据
    data = pd.read_csv(csv_file)
    data.columns = data.columns.str.lower()
    
    # 确保包含必要的列
    required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
    if not all(col in data.columns for col in required_cols):
        raise ValueError(f"CSV file must contain columns: {required_cols}")
    
    # 计算因子
    tech = TechnicalFactors(data)
    result = tech.calculate_all()
    
    return result


if __name__ == "__main__":
    # 测试代码
    import sys
    
    if len(sys.argv) > 1:
        csv_file = sys.argv[1]
        
        print(f"计算 {csv_file} 的技术因子...")
        
        # 计算所有因子
        factors = calculate_technical_factors(csv_file)
        
        print(f"\n因子计算完成！")
        print(f"因子数量: {len([col for col in factors.columns if col not in ['date', 'ts_code']])}")
        print(f"数据行数: {len(factors)}")
        print(f"\n前5行数据:")
        print(factors.head())
        
        print(f"\n因子统计:")
        print(factors.describe())
    else:
        print("用法: python technical_factors.py <csv_file>")
        print("示例: python technical_factors.py data/000001.csv")

