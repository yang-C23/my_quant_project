"""
ATR（Average True Range）移动止损指标

ATR是衡量市场波动性的经典指标，可用于设置动态止损位。

ATR Trailing Stop策略：
- 多头止损线 = 最高价 - N倍ATR
- 当价格回撤超过N倍ATR时，触发止损

这种止损方式根据市场波动性自适应调整，
在高波动期给予更大的容忍空间，低波动期则收紧止损。
"""

from __future__ import annotations

import backtrader as bt


class ATR(bt.Indicator):
    """
    平均真实波幅（Average True Range）
    
    计算方法:
    1. True Range = max(High-Low, abs(High-PrevClose), abs(Low-PrevClose))
    2. ATR = MA(True Range, period)
    
    Lines:
        - atr: ATR值
    """
    
    lines = ('atr',)
    params = (
        ('period', 14),  # 标准周期14
        ('movav', bt.indicators.MovingAverageSimple),  # 可选EMA或SMA
    )
    
    plotinfo = dict(
        plot=True,
        plotname='ATR',
        subplot=True,
    )
    
    def __init__(self):
        # 使用Backtrader内置的ATR指标
        self.lines.atr = bt.indicators.ATR(self.data, period=self.p.period)


class ATRTrailingStop(bt.Indicator):
    """
    ATR移动止损线
    
    根据ATR动态计算止损位：
    - 多头止损 = Highest(High, period) - multiplier * ATR
    
    Lines:
        - stop_loss: 止损线位置
        - atr: ATR值
        - distance: 当前价格到止损线的距离
    """
    
    lines = ('stop_loss', 'atr', 'distance')
    params = (
        ('atr_period', 14),      # ATR计算周期
        ('multiplier', 3.0),     # ATR倍数（默认3倍）
        ('lookback', 20),        # 最高价回溯周期
    )
    
    plotinfo = dict(
        plot=True,
        plotname='ATR移动止损',
        subplot=False,
    )
    
    plotlines = dict(
        stop_loss=dict(color='red', _name='止损线', linestyle='--'),
        atr=dict(_plotskip=True),
        distance=dict(_plotskip=True),
    )
    
    def __init__(self):
        # 计算ATR
        atr_indicator = bt.indicators.ATR(self.data, period=self.p.atr_period)
        self.lines.atr = atr_indicator
        
        # 计算lookback期间的最高价
        highest_high = bt.indicators.Highest(self.data.high, period=self.p.lookback)
        
        # 止损线 = 最高价 - multiplier * ATR
        self.lines.stop_loss = highest_high - self.p.multiplier * atr_indicator
        
        # 当前价格到止损线的距离
        self.lines.distance = self.data.close - self.lines.stop_loss


class ATRStopSignal(bt.Indicator):
    """
    ATR止损触发信号
    
    当收盘价跌破止损线时产生卖出信号。
    
    Lines:
        - stop_triggered: 触发止损时为1
        - stop_loss: 止损线
    """
    
    lines = ('stop_triggered', 'stop_loss')
    params = (
        ('atr_period', 14),
        ('multiplier', 3.0),
        ('lookback', 20),
    )
    
    plotinfo = dict(
        plot=True,
        plotname='ATR止损信号',
        subplot=True,
    )
    
    def __init__(self):
        # ATR止损线
        atr_stop = ATRTrailingStop(
            self.data,
            atr_period=self.p.atr_period,
            multiplier=self.p.multiplier,
            lookback=self.p.lookback,
        )
        
        self.lines.stop_loss = atr_stop.stop_loss
        
        # 当收盘价跌破止损线时触发
        self.lines.stop_triggered = self.data.close < atr_stop.stop_loss


class ATRPositionSizing(bt.Indicator):
    """
    基于ATR的仓位计算指标
    
    根据ATR和风险承受度计算合理的仓位大小。
    
    仓位计算公式：
    Position Size = (Account Equity * Risk%) / (ATR * Multiplier)
    
    Lines:
        - atr: ATR值
        - risk_per_share: 每股风险金额（ATR * multiplier）
    """
    
    lines = ('atr', 'risk_per_share')
    params = (
        ('atr_period', 14),
        ('multiplier', 2.0),     # 风险倍数
    )
    
    plotinfo = dict(
        plot=True,
        plotname='ATR风险度',
        subplot=True,
    )
    
    def __init__(self):
        atr_indicator = bt.indicators.ATR(self.data, period=self.p.atr_period)
        
        self.lines.atr = atr_indicator
        self.lines.risk_per_share = atr_indicator * self.p.multiplier


class VWAP(bt.Indicator):
    """
    成交量加权平均价格（Volume Weighted Average Price）
    
    VWAP = Σ(Price * Volume) / Σ(Volume)
    
    VWAP代表当日的平均成本，常用于日内交易：
    - 价格 > VWAP: 多数持有者盈利
    - 价格 < VWAP: 多数持有者亏损
    """
    
    lines = ('vwap',)
    params = (
        ('period', 20),  # 计算周期
    )
    
    plotinfo = dict(
        plot=True,
        plotname='VWAP',
        subplot=False,
    )
    
    plotlines = dict(
        vwap=dict(color='orange', _name='VWAP', linestyle='--'),
    )
    
    def __init__(self):
        # 典型价格 = (High + Low + Close) / 3
        typical_price = (self.data.high + self.data.low + self.data.close) / 3.0
        
        # 价格 * 成交量
        pv = typical_price * self.data.volume
        
        # VWAP = Σ(Price*Volume) / Σ(Volume)
        sum_pv = bt.indicators.SumN(pv, period=self.p.period)
        sum_volume = bt.indicators.SumN(self.data.volume, period=self.p.period)
        
        self.lines.vwap = sum_pv / (sum_volume + 1e-10)


class VWAPRatio(bt.Indicator):
    """
    价格相对VWAP的比率
    
    Ratio = Close / VWAP
    
    Lines:
        - ratio: Close/VWAP
        - above_vwap: 价格在VWAP之上时为1
    """
    
    lines = ('ratio', 'above_vwap')
    params = (
        ('period', 20),
    )
    
    plotinfo = dict(
        plot=True,
        plotname='VWAP比率',
        subplot=True,
        plotyhlines=[0.95, 1.0, 1.05],
    )
    
    def __init__(self):
        vwap = VWAP(self.data, period=self.p.period)
        
        self.lines.ratio = self.data.close / (vwap + 1e-10)
        self.lines.above_vwap = self.data.close > vwap

