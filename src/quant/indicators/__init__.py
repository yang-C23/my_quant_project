"""Custom indicators."""

from quant.indicators.amv import amv, amv_timing_signal
from quant.indicators.b1 import PRESETS as B1_PRESETS
from quant.indicators.b1 import B1Params, b1
from quant.indicators.brick_osc import PRESETS as BRICK_PRESETS
from quant.indicators.brick_osc import BrickParams, brick_osc
from quant.indicators.dual_trend import dual_trend
from quant.indicators.kdj import kdj
from quant.indicators.volume_patterns import single_needle_proxy, volume_patterns
from quant.indicators.zhixing_macd import zhixing_macd

__all__ = [
    "B1_PRESETS",
    "BRICK_PRESETS",
    "B1Params",
    "BrickParams",
    "amv",
    "amv_timing_signal",
    "b1",
    "brick_osc",
    "dual_trend",
    "kdj",
    "single_needle_proxy",
    "volume_patterns",
    "zhixing_macd",
]
