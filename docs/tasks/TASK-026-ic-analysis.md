# TASK-026: 因子 IC / 分层分析（qlib 接线）

- Milestone: M2　|　State: backlog
- Branch: `task/TASK-026-ic`　|　Depends: TASK-025

## Context
backtest_platform.md §1/§4（Tier2 入口）；ADR-0001。把布尔信号与连续指标值当因子做横截面评估，是 M6 因子模型的前置。

## Goal
`quant.research.ic` 对任意注册信号/因子输出 IC 报告（RankIC 序列、衰减、分层收益）。

## Scope
```python
# src/quant/signals/factors.py
def to_factor(name: str, symbols, start, end) -> pd.Series
    """index=(datetime, instrument)（qlib 惯例），值=连续打分或 {0.,1.}；封装 compute_signal。"""

# src/quant/research/ic.py
def rank_ic(factor: pd.Series, horizon: int = 1, *, universe="nostar", price="open_next") -> pd.DataFrame
    # 按日横截面 spearman(factor_t, ret_{t+1→t+1+h})；输出 date→ic 序列 + 汇总(mean, ir, t-stat)
def ic_decay(factor, horizons=(1,3,5,10,20)) -> pd.DataFrame
def quantile_returns(factor, q=5, horizon=5) -> pd.DataFrame        # 分层组合日均收益/累计曲线
def ic_report(name: str, ...) -> Path                               # 组装 md 报告到 backtest_results/
```
- CLI：`myquant ic <signal_name> --start … --end …`。
- 实现可用纯 pandas（不必强拉 qlib 的 analysis 模块），但 factor 的 MultiIndex 口径必须与 qlib 兼容（M6 直接喂 DatasetH）。

## Non-goals
因子预处理（去极值/中性化——M6）；ML 模型。

## Files to touch
`src/quant/research/ic.py`, `src/quant/signals/factors.py`, `src/quant/cli.py`, `tests/unit/test_ic.py`。

## Acceptance criteria
1. `pytest -q tests/unit/test_ic.py` 全绿：合成因子=未来收益本身 → IC≈1；随机因子 → |IC|≈0（统计界内）；分层单调性用例；前视保护（factor_t 对 ret 的窗口从 t+1 开始）用例。
2. 集成（审查者）：`myquant ic b1_v242_62 --start 2018-01-01 --end 2024-12-31` 出报告，IC 序列非空且样本天数正确。
3. `ruff` 全绿。

## Test plan
如上；布尔稀疏因子（B1 命中率低）横截面样本不足的日子跳过并计数。

## Notes / risks
布尔信号的日横截面命中数可能 <30 → RankIC 噪声大，报告需输出每日样本数分布并在 md 中提示解释边界；这正是后续把构件连续化（factors 而非 signals）的动机，写进报告模板的"下一步"栏。
