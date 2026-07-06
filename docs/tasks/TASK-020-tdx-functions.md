# TASK-020: quant.tdx.functions — 通达信原语库 + 黄金值体系

- Milestone: M2　|　State: backlog
- Branch: `task/TASK-020-tdx-functions`　|　Depends: TASK-004（可与 M1 并行）

## Context
docs/indicators/README.md 的原语语义表。这是全部指标移植的地基，语义错一处全体系皆错，因此用 v1 backtrader 实现生成黄金值锁死。

## Goal
`quant.tdx.functions` 提供语义 1:1 的向量化原语，黄金值测试全绿。

## Scope
1. **移动提交（纯 git mv）**：`src/quant/indicators/{kdj.py,kdj_tdx.py,dual_trend.py,volume_breath.py,brick.py}` → `tests/reference/bt_legacy/`（v1 backtrader 实现降级为测试参照；`src/quant/indicators/` 清空待新实现）。
2. `src/quant/tdx/functions.py`：`REF, MA, EMA, SMA, HHV, LLV, SUM, COUNT, CROSS, BARSLAST, EVERY, EXIST, IIF`（IF 避开关键字）, `MAX2, MIN2, ABS_`——全部 `pd.Series -> pd.Series`，语义见 README 表；SMA/EMA 用 `ewm(..., adjust=False)` 等价实现并处理 NaN 跳过（NaN 期间保持状态，恢复后继续递归）。
3. `tests/fixtures/generate_goldens.py`：读 `tests/fixtures/tdx/` 的 .day fixture → 用 `tests/reference/bt_legacy` 的 `TDXSMA`/`KDJTDX`/`DualTrend`/`VolumeBreath`/`BrickIndicator` 跑 backtrader → 输出 `tests/fixtures/goldens/{tdx_sma,kdj_tdx,dual_trend,volume_breath,brick}_<symbol>.csv`（提交进 git，每个 <100KB）。脚本可重跑（黄金值再生成说明写入 fixtures/README.md）。
4. `tests/unit/test_tdx_functions.py`：
   - 每个原语 vs 朴素逐 bar 参考实现（测试内 20 行循环版）在随机序列上全等（含 NaN 注入）；
   - `SMA`/`KDJTDX` 组合 vs 黄金 CSV rtol ≤ 1e-8。

## Non-goals
指标本体（021/022/…）；numba 加速（性能瓶颈出现再谈）。

## Files to touch
`src/quant/tdx/{__init__.py,functions.py}`, `tests/reference/bt_legacy/**`(移动), `tests/fixtures/generate_goldens.py`, `tests/fixtures/goldens/*.csv`, `tests/unit/test_tdx_functions.py`。

## Acceptance criteria
1. `pytest -q tests/unit/test_tdx_functions.py` 全绿。
2. `python tests/fixtures/generate_goldens.py --check` 重新生成并与已提交黄金值一致（证明可复现）。
3. `ruff` 全绿；`git log` 中移动为独立 commit。

## Test plan
如上。NaN 语义重点：序列开头 NaN（warmup）与中段 NaN（停牌）两种注入都要测。

## Notes / risks
- pandas `ewm(alpha=m/n, adjust=False, ignore_na=?)` 的 NaN 语义与 backtrader 递归实现可能不同——以黄金值为准绳，必要时手写递推循环（单符号内循环可接受，见 conventions）。
- `CROSS(A,B)` 在 A/B 任一为 NaN 的 bar 输出 False。
- `HHV(X,0)`（从头累计）v1 用到与否先查，未用到可 `NotImplementedError` 并注明。
