"""
成交量呼吸度指标（Volume Breath）

通达信原始逻辑：
计算N周期内的成交量"呼吸"程度，即高量与低量的差异度。

高量计算：
- VH1: N周期内最高成交量
- VH2: N周期内第二高成交量（排除VH1）
- VH3: N周期内第三高成交量（排除VH1, VH2）
- AVGHIGH = (VH1 + VH2 + VH3) / 3

低量计算：
- VL1: N周期内最低成交量
- VL2: N周期内第二低成交量（排除VL1）
- VL3: N周期内第三低成交量（排除VL1, VL2）
- AVGLOW = (VL1 + VL2 + VL3) / 3

呼吸度 = AVGHIGH / AVGLOW

当呼吸度 > 阈值（如3.5）时，说明该股票成交量有明显的放量缩量交替，
具有良好的"呼吸感"，适合做波段交易。
"""

from __future__ import annotations

import backtrader as bt
import numpy as np


class VolumeBreath(bt.Indicator):
    """
    成交量呼吸度指标
    
    Lines:
        - avghigh: 高量平均值（VH1+VH2+VH3)/3
        - avglow: 低量平均值（VL1+VL2+VL3)/3
        - breath_ratio: 呼吸度比率 AVGHIGH/AVGLOW
        - is_active: 呼吸度 > ratio_threshold 时为1
    """
    
    lines = ('avghigh', 'avglow', 'breath_ratio', 'is_active')
    params = (
        ('period', 30),         # 回溯周期
        ('ratio_threshold', 3.5),  # 呼吸度阈值
    )
    
    plotinfo = dict(
        plot=True,
        plotname='成交量呼吸度',
        subplot=True,
        plotyhlines=[1.0, 2.0, 3.5, 5.0],
    )
    
    plotlines = dict(
        breath_ratio=dict(color='blue', _name='呼吸比率'),
        avghigh=dict(_plotskip=True),
        avglow=dict(_plotskip=True),
        is_active=dict(_plotskip=True),
    )
    
    def __init__(self):
        # 使用prenext和next手动计算，因为需要排序逻辑
        pass
    
    def prenext(self):
        # 数据不足时，设置默认值
        self.lines.avghigh[0] = float('nan')
        self.lines.avglow[0] = float('nan')
        self.lines.breath_ratio[0] = 1.0
        self.lines.is_active[0] = 0.0
    
    def next(self):
        # 获取最近N期的成交量数据
        if len(self.data) < self.p.period:
            self.lines.avghigh[0] = float('nan')
            self.lines.avglow[0] = float('nan')
            self.lines.breath_ratio[0] = 1.0
            self.lines.is_active[0] = 0.0
            return
        
        # 提取最近period期的成交量
        volumes = [self.data.volume[-i] for i in range(self.p.period)]
        volumes = [v for v in volumes if v > 0]  # 过滤掉0或异常值
        
        if len(volumes) < 3:
            self.lines.avghigh[0] = float('nan')
            self.lines.avglow[0] = float('nan')
            self.lines.breath_ratio[0] = 1.0
            self.lines.is_active[0] = 0.0
            return
        
        # 排序
        sorted_volumes = sorted(volumes)
        
        # 计算高量（最大的3个）
        vh1 = sorted_volumes[-1] if len(sorted_volumes) >= 1 else 0
        vh2 = sorted_volumes[-2] if len(sorted_volumes) >= 2 else vh1
        vh3 = sorted_volumes[-3] if len(sorted_volumes) >= 3 else vh2
        avghigh = (vh1 + vh2 + vh3) / 3.0
        
        # 计算低量（最小的3个）
        vl1 = sorted_volumes[0] if len(sorted_volumes) >= 1 else 0
        vl2 = sorted_volumes[1] if len(sorted_volumes) >= 2 else vl1
        vl3 = sorted_volumes[2] if len(sorted_volumes) >= 3 else vl2
        avglow = (vl1 + vl2 + vl3) / 3.0
        
        # 计算呼吸比率
        if avglow > 0:
            breath_ratio = avghigh / avglow
        else:
            breath_ratio = 1.0
        
        # 更新指标值
        self.lines.avghigh[0] = avghigh
        self.lines.avglow[0] = avglow
        self.lines.breath_ratio[0] = breath_ratio
        self.lines.is_active[0] = 1.0 if breath_ratio > self.p.ratio_threshold else 0.0


class PriceVolumeCorrelation(bt.Indicator):
    """
    量价相关性指标
    
    计算价格变动率与成交量变动率之间的相关性。
    
    正相关：量价同升/同跌
    负相关：量价背离
    
    Lines:
        - correlation: 量价相关系数（-1到1）
    """
    
    lines = ('correlation',)
    params = (
        ('period', 20),  # 相关性计算周期
    )
    
    plotinfo = dict(
        plot=True,
        plotname='量价相关性',
        subplot=True,
        plotyhlines=[-1.0, -0.5, 0.0, 0.5, 1.0],
    )
    
    def __init__(self):
        # 价格收益率
        price_returns = bt.indicators.PercentChange(self.data.close, period=1)
        
        # 成交量变化率
        volume_returns = bt.indicators.PercentChange(self.data.volume, period=1)
        
        # 使用pandas风格的滚动相关性（需要在next中手动计算）
        # Backtrader没有内置的相关系数指标，需要自定义
        self.price_rets = price_returns
        self.volume_rets = volume_returns
    
    def prenext(self):
        self.lines.correlation[0] = 0.0
    
    def next(self):
        if len(self.data) < self.p.period:
            self.lines.correlation[0] = 0.0
            return
        
        # 提取最近period期的数据
        price_data = [self.price_rets[-i] for i in range(self.p.period)]
        volume_data = [self.volume_rets[-i] for i in range(self.p.period)]
        
        # 计算相关系数
        try:
            corr = np.corrcoef(price_data, volume_data)[0, 1]
            if np.isnan(corr):
                corr = 0.0
        except:
            corr = 0.0
        
        self.lines.correlation[0] = corr


class VolumePullback(bt.Indicator):
    """
    缩量回调指标
    
    判断当前成交量是否处于缩量状态。
    
    Lines:
        - ratio: 当前成交量 / N日平均成交量
        - is_low_volume: ratio < threshold时为1（缩量）
    """
    
    lines = ('ratio', 'is_low_volume')
    params = (
        ('period', 20),
        ('threshold', 0.7),  # 低于平均量的70%视为缩量
    )
    
    plotinfo = dict(
        plot=True,
        plotname='缩量指标',
        subplot=True,
        plotyhlines=[0.5, 0.7, 1.0, 1.5],
    )
    
    def __init__(self):
        # 平均成交量
        avg_volume = bt.indicators.SMA(self.data.volume, period=self.p.period)
        
        # 当前成交量与平均成交量的比率
        self.lines.ratio = self.data.volume / (avg_volume + 1e-10)
        
        # 是否缩量
        self.lines.is_low_volume = self.lines.ratio < self.p.threshold

