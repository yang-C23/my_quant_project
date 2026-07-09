# TASK-034 Review — AMV 组合级仓位开关（Tier2 overlay 预检）

- 分支：`task/TASK-034-amv-position-switch`（2b9609b）
- 审查者：Claude（规划/审查代理）
- 日期：2026-07-09
- 结论：**PASS**

## 验收命令复跑（审查者亲自执行）

| AC | 结果 |
|---|---|
| 1 单测 | ✅ 13 passed；overlay 手算字面量、shift(1) t+1 语义、开/平仓扣费、无 regime 路径零变、schema 校验各有用例；030 既有用例零改动 |
| 2 双跑确定性 | ✅ 审查者独立双跑 68.4s/64.7s，两个 run_id（c456b3e1…/e5a0c353…），14 项 metrics **逐位一致** |
| 3 基线回归 | ✅ `base_*` 六项与 TASK-030-review 附录有效基线**逐位一致**（overlay 未扰动基线路径） |
| 4 全量 | ✅ 187 passed / ruff check / ruff format --check / 硬编码 gate 全绿；白名单 4/4 |

## 反作弊栏核销

1 shift 缺失——AC1(b) 用例 + diff 核对 `shift(1)`，与 `evaluate_timing` 口径一致；2 开平仓不扣费——手算字面量用例含扣费日，`position_change` 0→1 计 open_cost、1→0 计 close_cost；3 基线扰动——AC1(c)+AC3 双保险通过；4 regime 恒 1——switches=96（≈13.7 次/年，与 R1 OOS 的 11.99 次/年量级一致）；5 exposure 假数——**审查者用 `build_variant_signal` 独立重建 regime：exposure 0.463657678781 / switches 96，与交付逐位相同**。

## 实现要点核对

- `amv.py`/`amv_timing.py` 零修改，仅 import（白名单纪律 ✓）；
- warmup 200 BDays（卡面 ≥140 ✓）；overlay 近似口径已写入 summary 报告头（✓）；
- `extract_metrics` 只读 return/bench/cost/turnover 四列，新增列不构成扰动。

## 规划者裁定（Tier2 overlay 证据）

| metric | base（mom_20 topk50 裸组合） | switched（AMV immediate 开关） |
|---|---:|---:|
| annualized_return | −0.1664 | **+0.0061** |
| max_drawdown（加和口径） | −2.252 | **−0.921** |
| excess_return_with_cost | −0.2080 | **−0.0355** |
| information_ratio | −0.770 | −0.140 |
| turnover_mean | 0.0667 | 0.0319 |
| exposure / switches | 1.00 / — | 0.464 / 96 |

**裁定：防御价值在组合层复现**（回撤降为 41%、年化由深负转平），与 R1 指数级证据
（三年 −7.9% 环境 +8%、回撤减半）方向一致。诚实口径提醒：base 是深度亏损因子，
"46% 时间空仓"对任何亏损基线都有机械性帮助——本表证明的是**风险控制价值**而非 alpha；
真实约束（T+1、板别涨跌停、逐笔费用）下的确认走 Tier3（backtrader，032 之后视 M3
进度立卡）。维持 R1-final-report 的排队顺位不变，不提前立 Tier3 卡。
