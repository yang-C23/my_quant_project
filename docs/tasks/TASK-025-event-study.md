# TASK-025: 前向收益事件研究引擎 + `myquant study`（M2 gate 卡）

- Milestone: M2　|　State: backlog
- Branch: `task/TASK-025-event-study`　|　Depends: TASK-014, TASK-021

## Context
backtest_platform.md §2（Tier1 语义逐条）§5（parity 要求）。v1 用 Backtrader 事件循环做这件事要数小时；v2 目标全市场 <2 分钟且结论与 v1 已发布报告一致——**这是"换引擎不换结论"的 gate 卡**。

## Goal
向量化事件研究引擎 + CLI + 与历史 kdj_j0 报告的 parity 通过。

## Scope
1. `src/quant/research/forward_returns.py`：
   - `run_event_study(...)` 签名与 `EventStudyResult`（`.per_symbol/.pooled/.by_year/.to_report()`）严格按 backtest_platform.md §2；
   - 入场过滤三条（t+1 停牌 / t+1 开盘一字涨停 / 数据尽头）以样本剔除实现，被剔除样本数进结果统计；
   - 收益口径：`ret_h = close_{entry_day + h - 1} / open_{entry_day} - 1`（entry_day = t+1；h=1 即入场日收盘）——先写 3 个手算微用例锁死口径再接真数据；
   - 市况分组：可选 `regime: pd.Series`（date→int，来自 amv_regime）输出分组统计。
2. `src/quant/reporting/report.py` 适配 EventStudyResult（沿用 CSV+MD 输出）。
3. CLI：`myquant study <config.yaml>`——schema 即 `configs/study_kdj_j13.yaml` 注释；`configs/study_kdj_j0_parity.yaml` 固化 v1 报告的全部参数（universe/区间/J 阈值/horizons）。
4. signals 层批量执行器：`compute_signal(name, symbols, start, end) -> pd.DataFrame(symbol,date,sig)`（groupby 并行，`concurrent.futures`，workers 来自 settings）。

## Non-goals
费用建模（Tier1 报告注明"未含费用"）；组合构建（TASK-030）。

## Files to touch
`src/quant/research/{__init__.py,forward_returns.py}`, `src/quant/signals/factors.py`, `src/quant/reporting/report.py`, `src/quant/cli.py`, `configs/study_kdj_j0_parity.yaml`, `tests/unit/test_forward_returns.py`。

## Acceptance criteria
1. `pytest -q tests/unit/test_forward_returns.py` 全绿：手算微用例（3 符号×30 bar 合成价、已知信号→已知 ret_h）；过滤用例（次日停牌/一字板被剔除且计数正确）；by_year 切分正确。
2. `ruff` 全绿。
3. **集成 = M2 gate（审查者）**：分两道——
   - 第一道（小样本对拍）：5 只样本股结果 vs `docs/parity/kdj_j0_20260311_222907_summary.csv` 全指标对齐；
   - 第二道（全市场）：`myquant study configs/study_kdj_j0_parity.yaml` vs `docs/parity/pipeline_kdj_forward_return_20260311_225334_summary.csv`——各 horizon 样本数**完全一致**、胜率差 ≤0.1pp、均值差 ≤5bps；全市场耗时 <2 分钟。任何超差在 review 文件逐项解释成因，禁止改容差过关（注意 parity/README 记录的离群值观察）。
4. 性能：`compute_signal` 对 5000 符号并行无内存爆炸（峰值 <16GB）。

## Test plan
如上。parity 前先用 10 只股票的小 universe 与 v1 引擎（临时脚本跑 bt_legacy 策略）做**同口径小样本对拍**，把口径 bug 消灭在全量前。

## Notes / risks
- v1 口径细节（signal bar 判定用前一 bar 的 J、入场 bar 的 open）以 `tests/reference/bt_legacy` 与 v1 `strategies.py` 源码为准——先读代码再写，别猜。
- 停牌日在 qlib 对齐日历后是 NaN 行——"t+1"必须是**下一交易日且该符号有数据**，跳过逻辑写清并测试。
