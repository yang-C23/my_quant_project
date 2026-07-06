# TASK-012: 向量化复权因子与基础量（adjust / basics）

- Milestone: M1　|　State: backlog
- Branch: `task/TASK-012-adjust`　|　Depends: TASK-011

## Context
data_platform.md §4（basics/adjust schema）§6（公式声明）。v1 `scripts/calc_basic.py`/`calc_factor.py` 算法正确（QUANTAXIS，经 4b51c91 修正）但逐符号 SQL+Python 循环（~12000 次往返 / 28M 行）。本卡向量化重写，**算法语义不变**。

## Goal
全市场 basics + adjust 两表在 staging 上向量化计算 ≤ 3 分钟。

## Scope
```python
# src/quant/etl/adjust.py
def theoretical_preclose(prev_close: pd.Series, ev: pd.DataFrame) -> pd.Series:
    """QUANTAXIS：(prev_close*10 - fenhong + peigu*peigujia) / (10 + songzhuangu + peigu)"""
def compute_adjust(daily: pd.DataFrame, gbbq: pd.DataFrame) -> pd.DataFrame:
    """返回 [symbol,date,hfq_factor,qfq_factor]。除权日 ratio=prev_close_实际/preclose_理论 …
    （与 v1 calc_factor.py 的 hfq 乘法部分逐符号语义一致，groupby+cumprod 向量化）；
    qfq_factor = hfq_factor / last(hfq_factor)。"""

# src/quant/etl/basics.py
def compute_basics(daily: pd.DataFrame, gbbq: pd.DataFrame) -> pd.DataFrame:
    """[symbol,date,preclose,pct_chg,amplitude,turnover,float_shares,total_shares,
    float_mktcap,total_mktcap]——股本时间线由 GBBQ 股本类记录 merge_asof 展开。"""
```
- CLI `etl full --steps derive` 接入。

## Non-goals
qlib dump；QFQ 减法式（v1 视图口径）——**不实现**，差异见 data_platform §6。

## Files to touch
`src/quant/etl/{adjust.py,basics.py}`, `src/quant/cli.py`, `tests/unit/test_adjust.py`, `tests/unit/test_basics.py`, `tests/fixtures/adjust/*.csv`。

## Acceptance criteria
1. `pytest -q tests/unit/test_adjust.py tests/unit/test_basics.py` 全绿，含：
   - 手工构造 4 用例：纯分红 / 纯送转 / 配股 / 分红+送转组合——hfq_factor 与手算值 rtol ≤ 1e-12；
   - 无除权符号 hfq 恒为 1；qfq 末日恒为 1；
   - **PG 黄金 fixture**：`tests/fixtures/adjust/pg_sz000001_adjust.csv`（从 PG `tdx.adjust_factor` 导出的 sz000001 全历史，生成 SQL 写进 fixtures/README）与 `compute_adjust` 输出 rtol ≤ 1e-9 对齐。
2. 集成（审查者）：全市场 derive 耗时 ≤ 3 分钟；抽 20 个含复杂除权史的符号与 PG 全对齐（此项在 TASK-016 系统化）。
3. `ruff` 全绿。

## Test plan
如上；股本时间线测试：GBBQ 股本变更日前后 float_shares 正确切换（merge_asof 边界：变更当日生效口径与 v1 一致——以 PG fixture 锁定）。

## Notes / risks
- 除权日 ratio 用的是**实际昨收/理论昨收**，注意别写反（v1 代码为准）。
- 停牌期间除权（除权日无交易）：事件落到复牌首日——v1 的处理方式先读懂再复刻，不确定处以 PG fixture 对齐为准绳。
- basics.turnover 需 float_shares>0 保护。
