# TASK-034: AMV 组合级仓位开关 — Tier2 overlay 预检（挂载 030 管线）

- Milestone: M3　|　State: ready
- Branch: `task/TASK-034-amv-position-switch`　|　Depends: TASK-030（已合并）, TASK-070（已合并）

## Context
R1 裁定（`docs/reviews/R1-final-report.md`）：AMV 择时的价值在防御（指数三年 −7.9% 环境下
+8%、回撤减半），采纳形态 = **原版 immediate** 变体（k=2.13, buy=4.0, sell=−2.3，非 confirm_life）
作组合级仓位开关，进 Tier3 验证队列。本卡是 Tier3 之前的 **Tier2 overlay 预检**：把 regime
开关叠加到 TASK-030 的 TopkDropout 日度收益上，量化"裸组合 vs 开关组合"的风险收益差，为
Tier3（backtrader，TASK-032 之后）是否立卡提供证据。基线现状（TASK-030-review 附录）：
mom_20 topk50 IS 年化 −16.6%、加和口径 mdd −2.25。

**Overlay 是近似**：假设开关日全仓↔空仓一步完成，只近似计费（见 Scope 3），不建模逐日
调仓路径——真实约束（T+1、涨跌停、逐笔费用）是 Tier3 的职责，报告头必须写明这一口径。

## Goal
`myquant backtest topk configs/backtest/topk_amv_switch.yaml`（带 `regime` 段的同一命令）输出
裸组合与开关组合的对照 metrics（含市场内天数占比），落 mlflow 与报告；数值确定性同 030。

## Scope
1. **配置扩展**（`qlib_topk.py`）：`regime` 可选段，schema：
   ```yaml
   regime:
     kind: amv_immediate        # 仅此一种，其他值报错
     index: sh999999            # regime 数据源指数
     k: 2.13
     buy_th: 4.0
     sell_th: -2.3
   ```
   无 `regime` 段时行为与现在完全一致（030 的既有单测不许动断言）。
2. **regime 构建**：`get_ohlcv(index, adjust="qfq")` 取全窗（含 warmup：start 前推 ≥140 交易日，
   实现取整段再切）→ `quant.indicators.amv.amv(df, k=k)` →
   `quant.research.amv_timing.build_variant_signal(..., variant="immediate")` → regime{0,1} 序列。
   **零修改复用**上述两个函数（它们不在白名单）。
3. **overlay 计算**（新增纯函数，放 `qlib_topk.py`）：
   ```python
   def apply_regime_overlay(
       report: pd.DataFrame,          # 030 的日度 report（return/bench/cost/turnover 列）
       regime: pd.Series,             # {0,1}，index=交易日
       *, switch_cost: float,         # 单边开/平近似费率 = exchange.open_cost+close_cost 之和的一半？No：
                                      # 开仓日计 open_cost、平仓日计 close_cost（一步全仓近似）
   ) -> pd.DataFrame:
       """position = regime.reindex(report.index).ffill().fillna(0).shift(1).fillna(0)
       （t 信号 → t+1 生效，与 evaluate_timing 口径一致，禁止未来函数）。
       overlay_return = report['return'] * position
       开仓日（position 0→1）额外扣 open_cost；平仓日（1→0）扣 close_cost；
       持仓日的原 cost 保留，空仓日 cost=0。返回加列后的 report 副本
       （overlay_return / overlay_cost / position）。"""
   ```
4. **metrics 与报告**：有 `regime` 段时，metrics 输出两套（前缀 `base_` / `switched_`）+
   `switched_exposure`（position 均值）+ `switches`（0↔1 次数）；summary md 加 base vs switched
   对照表；mlflow params 记 regime 四参。
5. 复用 `myquant backtest topk` 命令与确定性机制（PYTHONHASHSEED 子进程），不加新 CLI。

## Non-goals
不做 confirm_life 或任何阈值调参（R1 已裁定原版）；不改 TopkDropoutStrategy 内部（overlay
在 report 层）；不做 Tier3 backtrader 实现；不动 `indicators/amv.py`、`research/amv_timing.py`；
不下"是否采纳"结论（规划者在 review 裁定）。

## Files to touch
`src/quant/backtest/qlib_topk.py`, `configs/backtest/topk_amv_switch.yaml`, `tests/unit/test_qlib_topk.py`

## Acceptance criteria
1. `pytest -q tests/unit/test_qlib_topk.py`：新增用例全绿且既有用例零改动——
   (a) overlay 数学：合成 5 日 report + 已知 regime，`overlay_return`/开平仓扣费/`position`
   逐日断言为**手算字面量**；(b) shift 语义：regime 在 t 翻转，position 必须 t+1 才变
   （断言 t 日仍旧值）；(c) 无 regime 段时输出与 030 路径完全一致；(d) regime 段 schema
   校验（未知 kind / 缺参报错）。
2. `myquant backtest topk configs/backtest/topk_amv_switch.yaml` 全市场 IS 跑通两次完整命令，
   两个 mlflow run_id、`base_*` 与 `switched_*` 全部 metrics 逐位一致；耗时与
   `switched_exposure`、`switches` 写入 STATUS 备注。
3. `base_*` metrics 与 TASK-030-review 附录的有效基线数字逐位一致（同 universe 同配置，
   overlay 不得扰动基线路径）。
4. `pytest -q -m "not integration"` + `ruff check .` + `ruff format --check .` 全绿。

## 验收如何被作弊/退化满足？

1. **shift 缺失（未来函数）**：regime 当日生效会把开关的防御性夸大——AC1(b) 专门锁 t+1；
   审查者将 diff 检查 `shift(1)` 与 `evaluate_timing` 口径一致。
2. **开平仓不扣费**：切换成本归零让 switched 看起来更好——AC1(a) 的手算字面量含扣费日；
   审查者按 exchange 费率独立复算一个开+平周期。
3. **基线被扰动**：为了让对照好看而"顺手"改 030 路径——AC1(c) + AC3 双保险（既有用例
   零改动 + 基线数字逐位回归）。
4. **regime 恒为 1**：warmup 不足或指数取错时 regime 可能恒 1，对照表退化为两列相同也能
   "跑通"——AC2 要求上报 `switches` 次数；IS 段 AMV 原版应有约二十次上下切换（R1 findings
   量级），若 `switches`<5 视为异常，停下报告而非交付。
5. **exposure 假高/假低**：position 均值必须与 regime 序列独立可复算——审查者用
   `build_variant_signal` 重建 regime 核对。

## Test plan
overlay 纯函数用合成 report/regime 手算断言（AC1）；真实全市场走 AC2/AC3；不新增 fixture 文件。

## Notes / risks
- warmup：AMV 需 ~n×几十日历史，regime 构建取 start 前推 ≥140 交易日再切窗（照抄
  `scripts/r1_oos_final.py` 的 LOAD_START 处理模式）；切窗后首日 position 由 shift 自然为 0，
  属预期（首日空仓）。
- 指数 `sh999999` 与 `sh000001` 数据逐位相同（TASK-030 review 已验证），配置用 `sh999999`
  与 R1 口径保持一致。
- 报告头必须写"Tier2 overlay 近似（一步全仓切换 + 开/平仓单边计费），Tier3 以 backtrader
  为准"。
- 与 TASK-031 白名单零交集，可并行开发。
