# TASK-031: Backtrader A股基础件 — costs / feed / constraints

- Milestone: M3　|　State: ready
- Branch: `task/TASK-031-bt-feed-constraints`　|　Depends: TASK-014（已合并）

## Context
`docs/backtest_platform.md` §3（费用表与约束为**单一事实源**）；ADR-0001（backtrader = Tier3 验证器）。v1 参照：`git show 53f72fd^:src/quant/backtest/strategies.py`（is_suspended/is_upper_limit/is_lower_limit 三旗标思路）。本卡只做基础件，策略移植在 TASK-032。

## Goal
纯库三件套：A股费用模型、带旗标的数据 feed、可复用约束检查器；全部行为有合成数据回归测试锁定。

## Scope
```python
# src/quant/backtest/costs.py —— 费用单一事实源（backtest_platform.md §3 表）
@dataclass(frozen=True)
class AShareCosts:
    commission_rate: float = 2.5e-4   # 双边
    commission_min: float = 5.0
    stamp_tax_rate: float = 5e-4      # 仅卖出；2023-08-28 前为 1e-3
    transfer_fee_rate: float = 1e-5   # 双边（沪市口径，统一应用并注明）
    slippage_rate: float = 1e-3       # 默认，可配
    def stamp_rate_at(self, date: pd.Timestamp) -> float
    def side_cost(self, *, price: float, size: int, is_sell: bool, date: pd.Timestamp) -> float

class AShareCommission(bt.CommInfoBase):
    """backtrader 佣金桥：__init__(costs: AShareCosts)；_getcommission 按上表实现。"""

# src/quant/backtest/feed.py
class AShareDataFeed(bt.feeds.PandasData):
    lines = ("is_suspended", "limit_up_price", "limit_down_price", "raw_open")

def build_feed(symbol: str, start: str | None, end: str | None) -> AShareDataFeed:
    """qfq OHLCV + raw 旗标（口径同 research 载价：raw open→raw_open, suspended, limit_*_price），
    走 get_ohlcv_batch/get_ohlcv。停牌日保留 bar（旗标=True），价格 ffill 与 NaN 处理策略写 docstring。"""

# src/quant/backtest/constraints.py
class AShareConstraints:
    """无状态检查器 + T+1 台账。"""
    def can_buy(self, data) -> bool           # 当日非停牌 且 非一字涨停开盘(raw_open>=limit_up)
    def can_sell(self, data, size: int) -> bool  # 非停牌、非一字跌停开盘、且今日可卖数量>=size(T+1)
    def on_buy_filled(self, dt, size) -> None    # 登记 T+1 台账
    def sellable(self, dt) -> int                # 今日可卖股数
    @staticmethod
    def round_lots(size: int) -> int             # 向下取 100 股整数倍
```
- 一字板判定统一用 raw 价格对 `limit_up_price/limit_down_price`（数据已含分板计算结果，**不要**自己按 10%/20% 重算）。
- `src/quant/backtest/__init__.py` 导出三件套。

## Non-goals
策略/CLI/报告（TASK-032）；组合级多标的撮合调度；融资融券/保证金；qlib exchange（TASK-030 自带近似口径）。

## Files to touch
`src/quant/backtest/costs.py`, `src/quant/backtest/feed.py`, `src/quant/backtest/constraints.py`, `src/quant/backtest/__init__.py`, `tests/unit/test_bt_costs.py`, `tests/unit/test_bt_feed_constraints.py`, `tests/fixtures/`（合成 bar 数据）。

## Acceptance criteria
1. `pytest -q tests/unit/test_bt_costs.py`：万2.5 佣金、最低 5 元触发、印花仅卖出、2023-08-28 税率切换（前 0.1% 后 0.05%）、过户费双边——逐项数值断言到分。
2. `pytest -q tests/unit/test_bt_feed_constraints.py`：合成序列回归——(a) T+1：当日买当日卖被拒、次日可卖；(b) 一字涨停日 can_buy=False，普通涨停(盘中触板但非一字) can_buy=True；(c) 一字跌停日 can_sell=False；(d) 停牌日买卖皆拒；(e) round_lots(150)=100、round_lots(99)=0。
3. 最小 cerebro 冒烟（进单测）：20 根合成 bar 买入持有 → 期末现金 = 初始 − 成交额 − 佣金(≥5) − 过户，逐位断言；卖出再断言含印花。
4. `pytest -q -m "not integration"` + `ruff check .` 全绿。

## Test plan
全部合成 fixture，不依赖真实数据（build_feed 的真实数据路径由 TASK-032 的 parity 运行覆盖）。

## Notes / risks
- backtrader `PandasData` 自定义 lines 需同步 `params` 映射，NaN 旗标要转 float（bt lines 不存 bool/NaN 需哨兵值，约定 0/1 与 -1=缺失，docstring 写死）。
- 停牌日 bar 的处理决定 T+1 台账与 next() 步进语义——保留 bar + 旗标（对齐 v1 feed 做法），策略侧靠 can_buy/can_sell 拦截。
- 滑点默认 0.1% 在 costs 中定义，但 backtrader 侧建议用 `BackBroker.set_slippage_perc` 挂接；两处保持同源常量。
