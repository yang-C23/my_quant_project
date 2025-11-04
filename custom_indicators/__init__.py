"""
自定义技术指标库

包含通达信策略所需的所有核心指标：
- 知行双线系统
- KDJ指标
- 成交量呼吸度
- ATR移动止损
- VWAP

所有指标都是Backtrader的Indicator子类，可直接在策略中使用。
"""

from .zhixing_indicators import (
    ZhiXingShortTrend,
    ZhiXingMultiAverage,
    ZhiXingTrendSpread,
    PriceZoneIndicator,
)

from .kdj import (
    StochasticRSV,
    KDJ,
    KDJCross,
    JOversoldSignal,
)

from .volume_breath import (
    VolumeBreath,
    PriceVolumeCorrelation,
    VolumePullback,
)

from .atr_stop import (
    ATR,
    ATRTrailingStop,
    ATRStopSignal,
    ATRPositionSizing,
    VWAP,
    VWAPRatio,
)

__all__ = [
    # 知行指标
    'ZhiXingShortTrend',
    'ZhiXingMultiAverage',
    'ZhiXingTrendSpread',
    'PriceZoneIndicator',
    # KDJ指标
    'StochasticRSV',
    'KDJ',
    'KDJCross',
    'JOversoldSignal',
    # 成交量指标
    'VolumeBreath',
    'PriceVolumeCorrelation',
    'VolumePullback',
    # ATR指标
    'ATR',
    'ATRTrailingStop',
    'ATRStopSignal',
    'ATRPositionSizing',
    'VWAP',
    'VWAPRatio',
]
