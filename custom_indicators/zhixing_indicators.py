"""
知行交易系统核心指标实现

包含双趋势线系统：
- 知行短期趋势线（白线）: EMA(EMA(C, N1), N1)
- 知行多空线（黄线）: (MA(C,M1) + MA(C,M2) + MA(C,M3) + MA(C,M4)) / 4

这些指标是通达信策略的核心组件。
"""

from __future__ import annotations

import backtrader as bt


class ZhiXingShortTrend(bt.Indicator):
    """
    知行短期趋势线（白线）
    
    计算方法: EMA(EMA(Close, N1), N1)
    
    这是一个双重指数平滑移动平均线，对价格变化更敏感，
    用于捕捉短期趋势的快速变化。
    """
    
    lines = ('zhixing_short',)
    params = (
        ('period', 10),  # N1参数，默认10
    )
    
    plotinfo = dict(
        plot=True,
        plotname='知行短期趋势线',
        subplot=False,
    )
    
    plotlines = dict(
        zhixing_short=dict(
            color='white',
            _name='白线',
        )
    )
    
    def __init__(self):
        # 第一次EMA平滑
        ema1 = bt.indicators.EMA(self.data.close, period=self.p.period)
        # 第二次EMA平滑
        self.lines.zhixing_short = bt.indicators.EMA(ema1, period=self.p.period)


class ZhiXingMultiAverage(bt.Indicator):
    """
    知行多空线（黄线）
    
    计算方法: (MA(C,M1) + MA(C,M2) + MA(C,M3) + MA(C,M4)) / 4
    
    这是四条不同周期均线的平均值，代表中长期趋势方向。
    当价格在此线之上时，市场处于多头状态；之下则为空头状态。
    """
    
    lines = ('zhixing_multi',)
    params = (
        ('period1', 14),   # M1参数
        ('period2', 28),   # M2参数
        ('period3', 57),   # M3参数
        ('period4', 114),  # M4参数
    )
    
    plotinfo = dict(
        plot=True,
        plotname='知行多空线',
        subplot=False,
    )
    
    plotlines = dict(
        zhixing_multi=dict(
            color='yellow',
            _name='黄线',
        )
    )
    
    def __init__(self):
        # 计算四条简单移动平均线
        ma1 = bt.indicators.SMA(self.data.close, period=self.p.period1)
        ma2 = bt.indicators.SMA(self.data.close, period=self.p.period2)
        ma3 = bt.indicators.SMA(self.data.close, period=self.p.period3)
        ma4 = bt.indicators.SMA(self.data.close, period=self.p.period4)
        
        # 四线平均
        self.lines.zhixing_multi = (ma1 + ma2 + ma3 + ma4) / 4.0


class ZhiXingTrendSpread(bt.Indicator):
    """
    知行趋势价差指标
    
    计算白线与黄线的价差和价差率，用于判断趋势强度。
    
    Lines:
        - spread: 白线 - 黄线（绝对价差）
        - spread_pct: (白线 - 黄线) / 黄线 * 100（相对价差百分比）
    """
    
    lines = ('spread', 'spread_pct')
    params = (
        ('short_period', 10),
        ('ma_periods', (14, 28, 57, 114)),
    )
    
    plotinfo = dict(
        plot=True,
        plotname='趋势价差',
        subplot=True,
    )
    
    def __init__(self):
        # 使用已定义的指标
        short_line = ZhiXingShortTrend(self.data, period=self.p.short_period)
        multi_line = ZhiXingMultiAverage(
            self.data,
            period1=self.p.ma_periods[0],
            period2=self.p.ma_periods[1],
            period3=self.p.ma_periods[2],
            period4=self.p.ma_periods[3],
        )
        
        # 计算价差
        self.lines.spread = short_line - multi_line
        
        # 计算相对价差（避免除零）
        self.lines.spread_pct = (short_line - multi_line) / (multi_line + 1e-10) * 100.0


class PriceZoneIndicator(bt.Indicator):
    """
    价格区间位置指标
    
    计算收盘价在白线和黄线之间的相对位置。
    
    计算方法: (Close - 黄线) / (白线 - 黄线)
    
    解释:
        - 值为0: 价格在黄线上
        - 值为0.5: 价格在白黄线中间
        - 值为1: 价格在白线上
        - 值>1: 价格突破白线（强势）
        - 值<0: 价格跌破黄线（弱势）
    """
    
    lines = ('zone',)
    params = (
        ('short_period', 10),
        ('ma_periods', (14, 28, 57, 114)),
    )
    
    plotinfo = dict(
        plot=True,
        plotname='价格区间位置',
        subplot=True,
        plotyhlines=[0.0, 0.5, 1.0],
    )
    
    def __init__(self):
        short_line = ZhiXingShortTrend(self.data, period=self.p.short_period)
        multi_line = ZhiXingMultiAverage(
            self.data,
            period1=self.p.ma_periods[0],
            period2=self.p.ma_periods[1],
            period3=self.p.ma_periods[2],
            period4=self.p.ma_periods[3],
        )
        
        # 价格相对位置（避免除零）
        denominator = short_line - multi_line
        self.lines.zone = (self.data.close - multi_line) / (denominator + 1e-10)

