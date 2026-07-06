# TASK-020 Review（第 1 轮）

- 日期：2026-07-06　|　开发者 & 审查者：Claude (Fable 5)（自审模式，验收命令全部真实运行）
- 分支：`task/TASK-020-tdx-functions`（c0b34bb 移动 + d84cbfe 修复/恢复 + 576e827 实现）

## 验收命令运行结果

| # | 命令 | 结果 |
|---|---|---|
| 1 | `pytest -q tests/unit/test_tdx_functions.py` | PASS（14 用例：全部原语 vs 朴素逐 bar 参考实现（含前导/中段 NaN 注入）、SMA 黄金全程精确 rtol 1e-10、KDJ 组合 vs 黄金 rtol 1e-8 全程含 warmup NaN 区） |
| 2 | `python tests/fixtures/generate_goldens.py --check` | PASS（两符号可复现） |
| 3 | `ruff` 全绿；移动为独立 commit | PASS（c0b34bb 8×R100） |

补充：全套 36 单测在 `-W error::FutureWarning` 下通过（布尔条件统一经 `_cond_to_bool` 处理）。

## 范围修订（规划者权限）

- `src/quant/backtest/{engine.py,strategies.py}` 随指标一并移入 `tests/reference/bt_legacy/`：它们 import 被移走的指标且本身就是 M2/M3 parity 的参照物（architecture.md §5 一致）。src 下不留断链模块。
- `BrickIndicator` 从 TASK-004 删除前的历史（`53f72fd~1`）恢复至 bt_legacy——黄金值需要它。

## 语义发现（已回写文档）

1. **bt TDXSMA 时钟跟随输入线** → 对 RSV 这类带 warmup-NaN 的输入，bt 实际也是"首个有效值播种"——与 v2 语义一致，KDJ 黄金对比**全程精确**，无需收敛窗口（好于卡面预期）。
2. **bt 经典 EMA（SMA 种子）≠ TDX EMA（Y₀=X₀）**：影响 dual_trend 白线的黄金对比——已在 TASK-021 卡补对比窗口规则（bar ≥150，rtol 1e-6）。
3. RSV 除零口径：v1 用 `IF(denom==0, 0, …)`（非 NaN）——kdj.md 的"除零→NaN"描述与 v1 实测不符，TASK-021 实现按 v1/黄金口径取 0，文档届时一并修正。

## 结论

**PASS** —— 合并至 `v2`；TASK-021、TASK-023 置 `ready`。
