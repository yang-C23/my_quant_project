# TASK-021: 指标移植 — KDJ（TDX 变体）+ 双线趋势呼吸 V2.1

- Milestone: M2　|　State: backlog
- Branch: `task/TASK-021-kdj-dualtrend`　|　Depends: TASK-020

## Context
docs/indicators/kdj.md、docs/indicators/dual_trend.md（公式逐字 + 移植要点）。

## Goal
两个指标的向量化实现 + 信号注册，黄金值对齐。

## Scope
```python
# src/quant/indicators/kdj.py
def kdj(df: pd.DataFrame, *, n: int = 9, m1: int = 3, m2: int = 3) -> pd.DataFrame   # 列 k,d,j

# src/quant/indicators/dual_trend.py
def dual_trend(df: pd.DataFrame, *, n1: int = 10, m: tuple = (14,28,57,114),
               n_vol: int = 30, vol_ratio: float = 3.5, j_low: float = 13.0) -> pd.DataFrame
    # 列 white,yellow,j,avghigh,avglow,breath_active,zone_ok,
    #    sig_dual_trend_entry, sig_golden_cross, sig_dead_cross
    # 呼吸度按通达信 HHV(IF(...)) 原式实现（见 dual_trend.md 移植要点 1）

# src/quant/signals/registry.py
@register("kdj_oversold")      # J<13 → sig
@register("dual_trend_entry")  # XG（不含板块剔除）
def ...(symbol df) -> pd.Series[bool]
    # registry: get(name) / names()；signals 层负责 groupby(symbol) 批量调用与 universe 过滤
```

## Non-goals
B1（022）；事件研究接线（025）。

## Files to touch
`src/quant/indicators/{__init__.py,kdj.py,dual_trend.py}`, `src/quant/signals/{__init__.py,registry.py}`, `tests/unit/test_kdj.py`, `tests/unit/test_dual_trend.py`。

## Acceptance criteria
1. `pytest -q tests/unit/test_kdj.py`：vs 黄金 `kdj_tdx_*.csv` rtol ≤ 1e-8（两只 fixture 股票全历史段）。
2. `pytest -q tests/unit/test_dual_trend.py`：white/yellow vs 黄金 `dual_trend_*.csv` rtol ≤ 1e-8；呼吸度 vs 黄金 `volume_breath_*.csv` 的差异**逐日枚举并断言只发生在窗口内含重复量值的日子**（v1 是 sorted 语义，v2 是通达信 HHV(IF) 语义——差异必须被测试显式圈定，不许无解释放行）。
3. registry：`from quant.signals.registry import get; get("dual_trend_entry")` 可调用；重复注册报错。
4. `ruff` 全绿。

## Test plan
如上 + 手工构造呼吸度微用例（7 根 bar 手算 top3/bottom3）验证通达信语义本身正确。

## Notes / risks
呼吸度差异条款是本卡最费心处：先写微用例锁定新语义正确，再做与 v1 黄金的差异枚举。若差异日数量 >5% 需停下来报告规划者（可能实现有 bug 而非语义差异）。
