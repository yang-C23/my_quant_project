"""
知行双线呼吸策略（Dual Line Breath Strategy）

基于通达信选股逻辑的完整实现，包含：
- 双趋势线系统（白线、黄线）
- 成交量呼吸度筛选
- KDJ超卖信号
- 价格区间过滤
- ATR动态止损/止盈

策略核心逻辑：
==========
买入条件（必须同时满足）:
1. 趋势确认：白线 > 黄线（上升趋势）
2. 成交量活跃：AVGHIGH > 3.5 * AVGLOW（有呼吸感）
3. 超卖信号：J < 13（超卖修复机会）
4. 价格位置：黄线 < 收盘价 < 白线（回调到位）

卖出条件（任一触发）:
1. 止损：收盘价跌破黄线（趋势破坏）
2. 死叉：白线下穿黄线（趋势反转）
3. 止盈：价格回撤超过3倍ATR（保护利润）

仓位管理：
- 固定10%资金买入
- T+1约束：当日买入次日才能卖出

Usage Example
-------------

.. code-block:: bash

    python backtest_engine.py --symbol 000001.SZ \\
        --strategy custom_strategies.dual_line_breath:DualLineBreathStrategy \\
        --strategy-params position_pct=0.1 j_threshold=13

"""

from __future__ import annotations

import backtrader as bt  # type: ignore[import]
from custom_indicators import (
    ZhiXingShortTrend,
    ZhiXingMultiAverage,
    KDJ,
    VolumeBreath,
    ATRTrailingStop,
)

__all__ = ["DualLineBreathStrategy"]


class DualLineBreathStrategy(bt.Strategy):
    """
    知行双线呼吸策略
    
    完整实现通达信策略逻辑，包含买入4条件、卖出3条件。
    """

    params = (
        # 知行双线参数
        ('short_period', 10),          # 白线周期 N1
        ('ma_period1', 14),            # 黄线周期 M1
        ('ma_period2', 28),            # 黄线周期 M2
        ('ma_period3', 57),            # 黄线周期 M3
        ('ma_period4', 114),           # 黄线周期 M4
        # KDJ参数
        ('kdj_period', 9),             # KDJ周期
        ('kdj_k_period', 3),           # K平滑周期
        ('kdj_d_period', 3),           # D平滑周期
        ('j_threshold', 13),           # J值超卖阈值
        # 成交量呼吸度参数
        ('volume_period', 30),         # 成交量回溯周期
        ('volume_ratio_threshold', 3.5),  # 呼吸度阈值
        # ATR止损参数
        ('atr_period', 14),            # ATR周期
        ('atr_multiplier', 3.0),       # ATR止损倍数
        ('atr_lookback', 20),          # 最高价回溯周期
        # 仓位管理
        ('position_pct', 0.10),        # 固定10%资金买入
        # 其他
        ('printlog', True),            # 是否打印日志
    )

    def __init__(self) -> None:
        """初始化指标和信号"""
        
        # 知行双线指标
        self.white_line = ZhiXingShortTrend(
            self.data,
            period=self.p.short_period
        )
        self.yellow_line = ZhiXingMultiAverage(
            self.data,
            period1=self.p.ma_period1,
            period2=self.p.ma_period2,
            period3=self.p.ma_period3,
            period4=self.p.ma_period4,
        )
        
        # KDJ指标
        self.kdj = KDJ(
            self.data,
            period=self.p.kdj_period,
            period_k=self.p.kdj_k_period,
            period_d=self.p.kdj_d_period,
        )
        
        # 成交量呼吸度指标
        self.volume_breath = VolumeBreath(
            self.data,
            period=self.p.volume_period,
            ratio_threshold=self.p.volume_ratio_threshold,
        )
        
        # ATR移动止损指标
        self.atr_stop = ATRTrailingStop(
            self.data,
            atr_period=self.p.atr_period,
            multiplier=self.p.atr_multiplier,
            lookback=self.p.atr_lookback,
        )
        
        # 交叉信号
        self.golden_cross = bt.indicators.CrossUp(self.white_line, self.yellow_line)
        self.death_cross = bt.indicators.CrossDown(self.white_line, self.yellow_line)
        
        # 记录买入日期（用于T+1约束）
        self.buy_date = None
        
        # 用于跟踪最高点（止盈用）
        self.entry_price = None
        self.highest_since_entry = None
        
        # 交易记录
        self.trade_records = []

    def log(self, txt: str, dt=None) -> None:
        """日志输出"""
        if self.p.printlog:
            dt = dt or self.datas[0].datetime.date(0)
            print(f'{dt.isoformat()} {txt}')

    def notify_order(self, order) -> None:
        """订单状态通知"""
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(
                    f'买入执行, 价格: {order.executed.price:.2f}, '
                    f'成本: {order.executed.value:.2f}, '
                    f'手续费: {order.executed.comm:.2f}'
                )
                # 记录买入日期和价格
                self.buy_date = self.datas[0].datetime.date(0)
                self.entry_price = order.executed.price
                self.highest_since_entry = order.executed.price
                
                # 记录交易
                self.trade_records.append({
                    'type': 'buy',
                    'date': self.buy_date.isoformat(),
                    'price': order.executed.price,
                    'size': order.executed.size,
                    'value': order.executed.value,
                    'commission': order.executed.comm,
                })
                
            elif order.issell():
                self.log(
                    f'卖出执行, 价格: {order.executed.price:.2f}, '
                    f'成本: {order.executed.value:.2f}, '
                    f'手续费: {order.executed.comm:.2f}'
                )
                # 记录交易
                pnl = order.executed.price - self.entry_price if self.entry_price else 0
                pnl_pct = (pnl / self.entry_price * 100) if self.entry_price else 0
                
                self.trade_records.append({
                    'type': 'sell',
                    'date': self.datas[0].datetime.date(0).isoformat(),
                    'price': order.executed.price,
                    'size': order.executed.size,
                    'value': order.executed.value,
                    'commission': order.executed.comm,
                    'pnl': pnl * abs(order.executed.size),
                    'pnl_pct': pnl_pct,
                })
                
                # 清空记录
                self.buy_date = None
                self.entry_price = None
                self.highest_since_entry = None

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log('订单取消/保证金不足/拒绝')

    def notify_trade(self, trade) -> None:
        """交易结果通知"""
        if not trade.isclosed:
            return
        
        self.log(f'交易盈亏: 毛利 {trade.pnl:.2f}, 净利 {trade.pnlcomm:.2f}')

    def next(self) -> None:
        """
        策略核心逻辑
        
        在每个bar执行，判断买入/卖出信号。
        """
        
        # 获取当前数据
        current_date = self.datas[0].datetime.date(0)
        close_price = self.data.close[0]
        
        # ============ 卖出逻辑（优先判断） ============
        if self.position:
            # 更新持仓期间的最高价
            if self.highest_since_entry is not None and close_price > self.highest_since_entry:
                self.highest_since_entry = close_price
            
            # T+1约束：检查是否可以卖出（必须持有至少1天）
            can_sell = self.buy_date is None or current_date > self.buy_date
            
            if can_sell:
                # 卖出条件1：止损 - 收盘价跌破黄线
                if close_price < self.yellow_line[0]:
                    self.log(f'止损触发: 价格 {close_price:.2f} < 黄线 {self.yellow_line[0]:.2f}')
                    self.sell()
                    return
                
                # 卖出条件2：死叉 - 白线下穿黄线
                if self.death_cross[0]:
                    self.log(f'死叉触发: 白线下穿黄线')
                    self.sell()
                    return
                
                # 卖出条件3：ATR移动止盈 - 价格跌破止损线
                if close_price < self.atr_stop.stop_loss[0]:
                    self.log(
                        f'ATR止盈触发: 价格 {close_price:.2f} < '
                        f'止损线 {self.atr_stop.stop_loss[0]:.2f}'
                    )
                    self.sell()
                    return
        
        # ============ 买入逻辑 ============
        if not self.position:
            # 买入条件1: 趋势确认 - 白线 > 黄线
            cond_trend = self.white_line[0] > self.yellow_line[0]
            
            # 买入条件2: 成交量活跃 - 呼吸度 > 阈值
            cond_activity = self.volume_breath.is_active[0] > 0
            
            # 买入条件3: 超卖信号 - J < 阈值
            cond_oversold = self.kdj.j[0] < self.p.j_threshold
            
            # 买入条件4: 价格区间 - 黄线 < 收盘价 < 白线
            cond_price_zone = (
                self.yellow_line[0] < close_price < self.white_line[0]
            )
            
            # 所有条件同时满足才买入
            if cond_trend and cond_activity and cond_oversold and cond_price_zone:
                # 计算买入金额（账户总资产的10%）
                portfolio_value = self.broker.getvalue()
                buy_amount = portfolio_value * self.p.position_pct
                
                # 计算买入股数（确保是100的整数倍）
                size = int(buy_amount / close_price / 100) * 100
                
                if size >= 100:  # 至少1手
                    self.log(
                        f'买入信号: 白线={self.white_line[0]:.2f}, '
                        f'黄线={self.yellow_line[0]:.2f}, '
                        f'J={self.kdj.j[0]:.2f}, '
                        f'呼吸度={self.volume_breath.breath_ratio[0]:.2f}, '
                        f'买入{size}股'
                    )
                    self.buy(size=size)
                else:
                    self.log(f'资金不足，无法买入（需要至少1手）')

    def stop(self) -> None:
        """回测结束时的汇总"""
        self.log(
            f'(参数: 白线={self.p.short_period}, J阈值={self.p.j_threshold}, '
            f'呼吸度阈值={self.p.volume_ratio_threshold:.1f}) '
            f'期末资产: {self.broker.getvalue():.2f}',
            dt=self.datas[0].datetime.date(0)
        )
