"""
KDJ随机指标实现

KDJ是KD指标的扩展，通过引入J值来捕捉更敏感的超买超卖信号。

计算方法:
1. RSV = (Close - LLV(Low, N)) / (HHV(High, N) - LLV(Low, N)) * 100
2. K = SMA(RSV, M1, 1)
3. D = SMA(K, M2, 1)
4. J = 3*K - 2*D

标准参数: N=9, M1=3, M2=3
"""

from __future__ import annotations

import backtrader as bt


class StochasticRSV(bt.Indicator):
    """
    原始RSV指标（未平滑的随机值）
    
    RSV = (Close - LLV(Low, N)) / (HHV(High, N) - LLV(Low, N)) * 100
    
    表示收盘价在N周期内的相对位置，范围0-100。
    """
    
    lines = ('rsv',)
    params = (
        ('period', 9),
    )
    
    plotinfo = dict(
        plot=True,
        plotname='RSV',
        subplot=True,
        plotyhlines=[0, 20, 50, 80, 100],
    )
    
    def __init__(self):
        # 最近N日最高价和最低价
        highest = bt.indicators.Highest(self.data.high, period=self.p.period)
        lowest = bt.indicators.Lowest(self.data.low, period=self.p.period)
        
        # RSV计算（避免除零）
        range_hl = highest - lowest
        self.lines.rsv = (self.data.close - lowest) / (range_hl + 1e-10) * 100.0


class KDJ(bt.Indicator):
    """
    KDJ随机指标
    
    Lines:
        - k: K值（RSV的3日平滑）
        - d: D值（K值的3日平滑）
        - j: J值（3*K - 2*D，更敏感）
    
    交易信号:
        - J < 0: 极度超卖
        - J < 10: 超卖
        - J > 100: 极度超买
        - K上穿D: 金叉，买入信号
        - K下穿D: 死叉，卖出信号
    """
    
    lines = ('k', 'd', 'j')
    params = (
        ('period', 9),     # RSV周期
        ('period_k', 3),   # K平滑周期
        ('period_d', 3),   # D平滑周期
    )
    
    plotinfo = dict(
        plot=True,
        plotname='KDJ',
        subplot=True,
        plotyhlines=[0, 20, 50, 80, 100],
    )
    
    plotlines = dict(
        k=dict(color='blue', _name='K'),
        d=dict(color='yellow', _name='D'),
        j=dict(color='purple', _name='J', _fill_gt=('d', 'green'), _fill_lt=('d', 'red')),
    )
    
    def __init__(self):
        # 计算RSV
        rsv = StochasticRSV(self.data, period=self.p.period)
        
        # K值：RSV的指数移动平滑（通达信的SMA(RSV, 3, 1)等同于EMA权重为1/3）
        # 在backtrader中，我们使用SmoothedMovingAverage或EMA来近似
        # SMA(X, N, M) 中 M=1 表示完全权重，等同于 EMA with alpha=1/N
        self.lines.k = bt.indicators.EMA(rsv, period=self.p.period_k)
        
        # D值：K值的指数移动平滑
        self.lines.d = bt.indicators.EMA(self.lines.k, period=self.p.period_d)
        
        # J值：3*K - 2*D
        self.lines.j = 3.0 * self.lines.k - 2.0 * self.lines.d


class KDJCross(bt.Indicator):
    """
    KDJ金叉死叉信号指标
    
    Lines:
        - golden_cross: K上穿D时为1，其他为0
        - death_cross: K下穿D时为1，其他为0
    """
    
    lines = ('golden_cross', 'death_cross')
    params = (
        ('period', 9),
        ('period_k', 3),
        ('period_d', 3),
    )
    
    plotinfo = dict(
        plot=True,
        plotname='KDJ交叉信号',
        subplot=True,
    )
    
    def __init__(self):
        kdj = KDJ(self.data, period=self.p.period, period_k=self.p.period_k, period_d=self.p.period_d)
        
        # K上穿D（金叉）
        self.lines.golden_cross = bt.indicators.CrossUp(kdj.k, kdj.d)
        
        # K下穿D（死叉）
        self.lines.death_cross = bt.indicators.CrossDown(kdj.k, kdj.d)


class JOversoldSignal(bt.Indicator):
    """
    J值超卖信号指标
    
    当J值低于阈值时产生超卖信号，这是买入的重要参考。
    
    Lines:
        - oversold: J < threshold时为1，否则为0
        - j_value: 原始J值
    """
    
    lines = ('oversold', 'j_value')
    params = (
        ('period', 9),
        ('period_k', 3),
        ('period_d', 3),
        ('threshold', 13),  # 超卖阈值，可设为0, 10, 13等
    )
    
    plotinfo = dict(
        plot=True,
        plotname='J超卖信号',
        subplot=True,
        plotyhlines=[0],
    )
    
    def __init__(self):
        kdj = KDJ(self.data, period=self.p.period, period_k=self.p.period_k, period_d=self.p.period_d)
        
        self.lines.j_value = kdj.j
        self.lines.oversold = kdj.j < self.p.threshold

