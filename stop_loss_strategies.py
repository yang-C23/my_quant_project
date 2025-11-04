"""
增强止损策略库
===============
提供多种止损方法供选择

包含：
1. 固定比例止损
2. ATR追踪止损
3. 布林带止损
4. 移动平均止损
5. 时间止损
6. 盈亏比止损
7. 回撤止损
8. 组合止损
"""

import backtrader as bt
import numpy as np
from typing import Optional, Tuple


class StopLossBase:
    """止损基类"""
    
    def __init__(self, data, entry_price: float):
        """
        初始化止损
        
        Parameters
        ----------
        data
            Backtrader数据源
        entry_price : float
            入场价格
        """
        self.data = data
        self.entry_price = entry_price
        self.highest_since_entry = entry_price
    
    def update(self, current_price: float):
        """更新止损状态"""
        if current_price > self.highest_since_entry:
            self.highest_since_entry = current_price
    
    def should_stop(self, current_price: float) -> Tuple[bool, str]:
        """
        判断是否应该止损
        
        Returns
        -------
        Tuple[bool, str]
            (是否止损, 止损原因)
        """
        raise NotImplementedError


class FixedPercentStopLoss(StopLossBase):
    """
    固定比例止损
    
    当亏损超过设定比例时止损
    """
    
    def __init__(self, data, entry_price: float, stop_loss_pct: float = 0.05):
        """
        Parameters
        ----------
        stop_loss_pct : float
            止损比例（如0.05表示5%）
        """
        super().__init__(data, entry_price)
        self.stop_loss_pct = stop_loss_pct
        self.stop_price = entry_price * (1 - stop_loss_pct)
    
    def should_stop(self, current_price: float) -> Tuple[bool, str]:
        """固定止损"""
        if current_price <= self.stop_price:
            return True, f'Fixed Stop Loss ({self.stop_loss_pct*100:.1f}%)'
        return False, ''


class TrailingStopLoss(StopLossBase):
    """
    移动止损（追踪止损）
    
    止损线随价格上涨而上移，但不下移
    """
    
    def __init__(self, data, entry_price: float, trailing_pct: float = 0.10):
        """
        Parameters
        ----------
        trailing_pct : float
            追踪止损比例（如0.10表示10%）
        """
        super().__init__(data, entry_price)
        self.trailing_pct = trailing_pct
    
    def should_stop(self, current_price: float) -> Tuple[bool, str]:
        """移动止损"""
        self.update(current_price)
        stop_price = self.highest_since_entry * (1 - self.trailing_pct)
        
        if current_price <= stop_price:
            return True, f'Trailing Stop ({self.trailing_pct*100:.1f}%)'
        return False, ''


class ATRStopLoss(StopLossBase):
    """
    ATR止损
    
    基于ATR（平均真实波幅）的动态止损
    """
    
    def __init__(self, data, entry_price: float, atr_multiplier: float = 2.0, atr_period: int = 14):
        """
        Parameters
        ----------
        atr_multiplier : float
            ATR倍数
        atr_period : int
            ATR计算周期
        """
        super().__init__(data, entry_price)
        self.atr_multiplier = atr_multiplier
        self.atr_period = atr_period
        
        # 计算ATR（简化实现）
        self.calculate_atr()
    
    def calculate_atr(self):
        """计算ATR"""
        # 简化实现：使用过去N天的价格波动
        if len(self.data) >= self.atr_period:
            high_low = [self.data.high[-i] - self.data.low[-i] for i in range(self.atr_period)]
            self.atr = np.mean(high_low)
        else:
            self.atr = (self.data.high[0] - self.data.low[0])
    
    def should_stop(self, current_price: float) -> Tuple[bool, str]:
        """ATR止损"""
        self.update(current_price)
        self.calculate_atr()
        
        stop_price = self.highest_since_entry - self.atr_multiplier * self.atr
        
        if current_price <= stop_price:
            return True, f'ATR Stop ({self.atr_multiplier}x ATR)'
        return False, ''


class BollingerBandStopLoss(StopLossBase):
    """
    布林带止损
    
    当价格跌破布林带下轨时止损
    """
    
    def __init__(self, data, entry_price: float, period: int = 20, num_std: float = 2.0):
        """
        Parameters
        ----------
        period : int
            布林带周期
        num_std : float
            标准差倍数
        """
        super().__init__(data, entry_price)
        self.period = period
        self.num_std = num_std
    
    def calculate_bollinger_bands(self) -> Tuple[float, float, float]:
        """计算布林带"""
        if len(self.data) >= self.period:
            closes = [self.data.close[-i] for i in range(self.period)]
            ma = np.mean(closes)
            std = np.std(closes)
            
            upper = ma + self.num_std * std
            lower = ma - self.num_std * std
            
            return upper, ma, lower
        return None, None, None
    
    def should_stop(self, current_price: float) -> Tuple[bool, str]:
        """布林带止损"""
        upper, ma, lower = self.calculate_bollinger_bands()
        
        if lower is not None and current_price < lower:
            return True, 'Bollinger Band Stop (Below Lower Band)'
        return False, ''


class MAStopLoss(StopLossBase):
    """
    移动平均止损
    
    当价格跌破移动平均线时止损
    """
    
    def __init__(self, data, entry_price: float, ma_period: int = 20):
        """
        Parameters
        ----------
        ma_period : int
            移动平均周期
        """
        super().__init__(data, entry_price)
        self.ma_period = ma_period
    
    def calculate_ma(self) -> Optional[float]:
        """计算移动平均"""
        if len(self.data) >= self.ma_period:
            closes = [self.data.close[-i] for i in range(self.ma_period)]
            return np.mean(closes)
        return None
    
    def should_stop(self, current_price: float) -> Tuple[bool, str]:
        """移动平均止损"""
        ma = self.calculate_ma()
        
        if ma is not None and current_price < ma:
            return True, f'MA Stop (Below MA{self.ma_period})'
        return False, ''


class TimeBasedStopLoss(StopLossBase):
    """
    时间止损
    
    持仓超过一定天数后强制平仓
    """
    
    def __init__(self, data, entry_price: float, max_holding_days: int = 10):
        """
        Parameters
        ----------
        max_holding_days : int
            最大持仓天数
        """
        super().__init__(data, entry_price)
        self.max_holding_days = max_holding_days
        self.entry_date_idx = len(data)
    
    def should_stop(self, current_price: float) -> Tuple[bool, str]:
        """时间止损"""
        holding_days = len(self.data) - self.entry_date_idx
        
        if holding_days >= self.max_holding_days:
            return True, f'Time Stop ({self.max_holding_days} days)'
        return False, ''


class ProfitTargetStopLoss(StopLossBase):
    """
    盈亏比止损
    
    达到目标盈利后止盈，同时设置止损
    """
    
    def __init__(
        self,
        data,
        entry_price: float,
        profit_target_pct: float = 0.15,
        stop_loss_pct: float = 0.05
    ):
        """
        Parameters
        ----------
        profit_target_pct : float
            目标盈利比例
        stop_loss_pct : float
            止损比例
        """
        super().__init__(data, entry_price)
        self.profit_target_pct = profit_target_pct
        self.stop_loss_pct = stop_loss_pct
        
        self.profit_target = entry_price * (1 + profit_target_pct)
        self.stop_loss = entry_price * (1 - stop_loss_pct)
    
    def should_stop(self, current_price: float) -> Tuple[bool, str]:
        """盈亏比止损"""
        if current_price >= self.profit_target:
            return True, f'Profit Target ({self.profit_target_pct*100:.1f}%)'
        
        if current_price <= self.stop_loss:
            return True, f'Stop Loss ({self.stop_loss_pct*100:.1f}%)'
        
        return False, ''


class DrawdownStopLoss(StopLossBase):
    """
    回撤止损
    
    当从最高点回撤超过一定比例时止损
    """
    
    def __init__(self, data, entry_price: float, max_drawdown_pct: float = 0.15):
        """
        Parameters
        ----------
        max_drawdown_pct : float
            最大回撤比例
        """
        super().__init__(data, entry_price)
        self.max_drawdown_pct = max_drawdown_pct
    
    def should_stop(self, current_price: float) -> Tuple[bool, str]:
        """回撤止损"""
        self.update(current_price)
        
        drawdown = (self.highest_since_entry - current_price) / self.highest_since_entry
        
        if drawdown >= self.max_drawdown_pct:
            return True, f'Drawdown Stop ({drawdown*100:.1f}%)'
        return False, ''


class CombinedStopLoss(StopLossBase):
    """
    组合止损
    
    结合多种止损方法，任一触发即止损
    """
    
    def __init__(
        self,
        data,
        entry_price: float,
        use_fixed: bool = True,
        use_trailing: bool = True,
        use_atr: bool = False,
        use_time: bool = True,
        fixed_pct: float = 0.08,
        trailing_pct: float = 0.12,
        atr_multiplier: float = 2.0,
        max_holding_days: int = 15
    ):
        """
        Parameters
        ----------
        use_fixed : bool
            是否使用固定止损
        use_trailing : bool
            是否使用追踪止损
        use_atr : bool
            是否使用ATR止损
        use_time : bool
            是否使用时间止损
        fixed_pct : float
            固定止损比例
        trailing_pct : float
            追踪止损比例
        atr_multiplier : float
            ATR倍数
        max_holding_days : int
            最大持仓天数
        """
        super().__init__(data, entry_price)
        
        self.stop_methods = []
        
        if use_fixed:
            self.stop_methods.append(FixedPercentStopLoss(data, entry_price, fixed_pct))
        
        if use_trailing:
            self.stop_methods.append(TrailingStopLoss(data, entry_price, trailing_pct))
        
        if use_atr:
            self.stop_methods.append(ATRStopLoss(data, entry_price, atr_multiplier))
        
        if use_time:
            self.stop_methods.append(TimeBasedStopLoss(data, entry_price, max_holding_days))
    
    def should_stop(self, current_price: float) -> Tuple[bool, str]:
        """组合止损"""
        for stop_method in self.stop_methods:
            should_stop, reason = stop_method.should_stop(current_price)
            if should_stop:
                return True, reason
        
        return False, ''


# ===================================================================
# 预定义止损方案
# ===================================================================

def get_stop_loss_strategy(
    strategy_name: str,
    data,
    entry_price: float,
    **kwargs
) -> StopLossBase:
    """
    获取止损策略
    
    Parameters
    ----------
    strategy_name : str
        策略名称：
        - 'conservative': 保守型（固定5%止损）
        - 'moderate': 稳健型（固定8%止损 + 时间止损15天）
        - 'aggressive': 激进型（追踪12%止损）
        - 'atr': ATR止损（2倍ATR）
        - 'combined': 组合止损（推荐）
    data
        Backtrader数据源
    entry_price : float
        入场价格
    **kwargs
        额外参数
    
    Returns
    -------
    StopLossBase
        止损策略实例
    """
    if strategy_name == 'conservative':
        # 保守型：固定5%止损
        return FixedPercentStopLoss(data, entry_price, stop_loss_pct=0.05)
    
    elif strategy_name == 'moderate':
        # 稳健型：固定8%止损 + 时间止损
        return CombinedStopLoss(
            data, entry_price,
            use_fixed=True,
            use_trailing=False,
            use_atr=False,
            use_time=True,
            fixed_pct=0.08,
            max_holding_days=15
        )
    
    elif strategy_name == 'aggressive':
        # 激进型：追踪12%止损
        return TrailingStopLoss(data, entry_price, trailing_pct=0.12)
    
    elif strategy_name == 'atr':
        # ATR止损
        atr_multiplier = kwargs.get('atr_multiplier', 2.0)
        return ATRStopLoss(data, entry_price, atr_multiplier=atr_multiplier)
    
    elif strategy_name == 'combined':
        # 组合止损（推荐）
        return CombinedStopLoss(
            data, entry_price,
            use_fixed=True,
            use_trailing=True,
            use_atr=False,
            use_time=True,
            fixed_pct=kwargs.get('fixed_pct', 0.08),
            trailing_pct=kwargs.get('trailing_pct', 0.12),
            max_holding_days=kwargs.get('max_holding_days', 20)
        )
    
    elif strategy_name == 'profit_target':
        # 盈亏比止损
        return ProfitTargetStopLoss(
            data, entry_price,
            profit_target_pct=kwargs.get('profit_target_pct', 0.15),
            stop_loss_pct=kwargs.get('stop_loss_pct', 0.05)
        )
    
    elif strategy_name == 'drawdown':
        # 回撤止损
        return DrawdownStopLoss(
            data, entry_price,
            max_drawdown_pct=kwargs.get('max_drawdown_pct', 0.15)
        )
    
    else:
        raise ValueError(f"Unknown stop loss strategy: {strategy_name}")


# ===================================================================
# 使用示例
# ===================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("增强止损策略库")
    print("=" * 60)
    
    print("\n可用的止损策略：")
    print("1. conservative  - 保守型（固定5%止损）")
    print("2. moderate      - 稳健型（固定8%止损 + 时间止损15天）")
    print("3. aggressive    - 激进型（追踪12%止损）")
    print("4. atr           - ATR止损（2倍ATR）")
    print("5. combined      - 组合止损（推荐：固定8% + 追踪12% + 时间20天）")
    print("6. profit_target - 盈亏比止损（止盈15% + 止损5%）")
    print("7. drawdown      - 回撤止损（最大回撤15%）")
    
    print("\n使用方法：")
    print("""
# 在策略中使用
from stop_loss_strategies import get_stop_loss_strategy

class MyStrategy(bt.Strategy):
    def __init__(self):
        self.stop_loss = None
    
    def next(self):
        if not self.position:
            # 买入
            self.buy()
            # 初始化止损
            self.stop_loss = get_stop_loss_strategy(
                'combined',
                self.data,
                self.data.close[0]
            )
        else:
            # 检查止损
            should_stop, reason = self.stop_loss.should_stop(self.data.close[0])
            if should_stop:
                self.sell()
                print(f'Stop Loss Triggered: {reason}')
    """)

