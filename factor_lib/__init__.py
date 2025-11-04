"""
Factor library package initialization.

Modules include custom factor implementations and references
to external factor libraries such as Alpha101.
"""

# 导出主要因子类
from .custom_factors import (
    TrendSpreadFactor,
    PriceZoneFactor,
    KDJ_JFactor,
    KDJ_SpreadFactor,
    VolumeBreathRatioFactor,
    PriceVolumeCorrelationFactor,
    VolumePullbackFactor,
    VWAPRatioFactor,
    ATRPositionFactor,
    RSVFactor
)

from .alpha101_factors import Alpha101Factors
from .technical_factors import TechnicalFactors
from .industry_factors import IndustryFactors
from .preprocessing import FactorPreprocessor
from .ic_analysis import FactorAnalyzer

__all__ = [
    # Custom factors
    "TrendSpreadFactor",
    "PriceZoneFactor",
    "KDJ_JFactor",
    "KDJ_SpreadFactor",
    "VolumeBreathRatioFactor",
    "PriceVolumeCorrelationFactor",
    "VolumePullbackFactor",
    "VWAPRatioFactor",
    "ATRPositionFactor",
    "RSVFactor",
    # Alpha factors
    "Alpha101Factors",
    "TechnicalFactors",
    "IndustryFactors",
    # Tools
    "FactorPreprocessor",
    "FactorAnalyzer",
]
