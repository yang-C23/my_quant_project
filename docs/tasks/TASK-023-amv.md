# TASK-023: 指标移植 — 活跃市值 0AMV + 择时信号状态机

- Milestone: M2　|　State: backlog
- Branch: `task/TASK-023-amv`　|　Depends: TASK-020（021 可并行）

## Context
docs/indicators/amv_0amv.md（公式逐字 + 择时规则 + 接口）。指数级择时是用户体系的"则时"核心。

## Goal
`amv()` 合成序列 + `amv_timing_signal()` 状态机可用，能对上证指数出历史买卖点表。

## Scope
按 amv_0amv.md 的接口章节实现：
- `src/quant/indicators/amv.py`：`amv(df, *, n=10, k=2.13)`（列 amv_open/high/low/close, amv_pct, amv_life）；
- `amv_timing_signal(amv_df, *, buy_th=4.0, sell_th=-2.3)`：
  - `sig_amv_buy`：`amv_pct ≥ buy_th` **或** `amv_pct + amv_pct.shift(1) ≥ buy_th`；
  - `sig_amv_sell`：`amv_pct ≤ sell_th`；
  - `regime`：状态机——buy 触发进入 1（持有），此后遇 sell 触发回到 0；初始 0；同日先 sell 后 buy 不存在（同一 bar sell 优先，保守）；
- `signals/registry.py` 注册 `amv_regime`（供事件研究做市况分组用）。
- CLI 便捷：`myquant study` 的配置支持 `regime_by: amv`（实际接线在 TASK-025，本卡只保证函数就绪）。

## Non-goals
K 系数重拟合与阈值泛化性研究（M6 研究卡，amv_0amv.md 要点 3）；个股级 AMV。

## Files to touch
`src/quant/indicators/amv.py`, `src/quant/signals/registry.py`, `tests/unit/test_amv.py`, `tests/fixtures/tdx/lday/sh999999.day`(若 TASK-010 未含，补充加长版指数 fixture ≥ 300 根)。

## Acceptance criteria
1. `pytest -q tests/unit/test_amv.py` 全绿：
   - 公式逐项：`amv_close == SMA(amount,10,1)/1e6 * close / MA(close.shift(1),5) * 0.1 * k`（用 tdx.functions 组合对照，rtol 1e-12）；
   - 状态机合成用例：构造 pct 序列 [5,-1,-2.4,3,2, ...] 断言 regime 翻转位置（含两日累计触发、连续 buy 不重复开仓、sell 后再 buy）；
   - k=2.07 参数传递生效。
2. 集成（审查者）：对真实上证指数跑 2023–2025 段，打印买卖信号日期表，人工抽查与笔记案例（"9月4日 −2.52%"型事件）方向一致。
3. `ruff` 全绿。

## Test plan
如上；amount 为 0/NaN 的极端 bar（指数不停牌，但数据缺口可能有）不炸。

## Notes / risks
- 指数 amount 的单位（元）与 /1e6 缩放只影响绝对值不影响 pct 信号——但 amv_life/绝对值要与通达信同刻度才好目视对比，保持原式。
- 两日累计口径 = 简单加和（amv_0amv.md 要点 2），别写成复利。
