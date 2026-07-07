# TASK-063: 研究 — 双线持仓规则量化（金叉→退出的成对交易）

- Milestone: R1　|　State: backlog
- Branch: `task/TASK-063-research-dualtrend`　|　Depends: TASK-060

## Context
docs/indicators/dual_trend.md 用法规则。双线是**持仓型**体系，固定 horizon 事件研究不适配——需要成对交易评估器（入场信号→退出信号闭环）。

## Goal
量化 z哥口播规则："金叉持有到死叉" vs "跌破白线减仓" vs "区间 B1 低吸"三种玩法在 IS 段的真实战绩；退出策略对比。候选 ≤2 组交 OOS。

## Scope
1. `src/quant/research/trade_pairs.py`：
   ```python
   def run_pair_study(entry_sig, exit_rules, prices, *, entry_filters="ashare",
                      max_hold=120, stop_loss=None) -> PairStudyResult
       # 每符号：entry 信号 t → t+1 开盘入场 → 首个满足的 exit 规则 →(t_exit+1) 开盘出场；
       # exit_rules: dict[name, bool Series]（如 dead_cross / close<white / 止损线）；
       # 输出每笔交易（含退出原因）、持有天数分布、收益分布、盈亏比、
       # 最大不利偏移（MAE）/最大有利偏移（MFE）——退出策略研究的核心证据。
   ```
   同样 t+1 纪律、ashare 过滤、无前视（exit 信号 t 判定 → t+1 开盘执行）。
2. **对照矩阵**（entry 固定 = sig_golden_cross）×（exit ∈ 死叉 / close<white 连续2日 / close<yellow / 固定止损8% / 死叉+止损组合）；
   另一组 entry = sig_dual_trend_entry（区间 B1 低吸）× 同退出矩阵。
3. 报告含 regime 分层与"假金叉"统计（金叉后 N≤5 日内死叉的比例及其损耗）。
4. `configs/research/dual_trend.yaml` + `docs/research/findings/TASK-063.md`。

## Non-goals
仓位管理（放飞 1/3 等——Tier3/M6）；周线级别；组合级资金曲线（Tier2/3 的事）。

## Files to touch
`src/quant/research/trade_pairs.py`, `tests/unit/test_trade_pairs.py`, `configs/research/dual_trend.yaml`, `docs/research/findings/TASK-063.md`。

## Acceptance criteria
1. `pytest -q tests/unit/test_trade_pairs.py`：合成序列手算对齐（含：入场后立即死叉、max_hold 截断、止损与信号同日的优先级=止损先行、MAE/MFE 手算）。
2. 复现命令跑通并复现 findings 数字（IS 段）。
3. findings 含：两个 entry × 五退出的完整矩阵（笔数/胜率/盈亏比/平均持有天/MAE/MFE）、假金叉统计、候选 ≤2 组。
4. ruff/全套绿；无 2022+ 数字。

## Notes / risks
- 同符号重叠信号处理：持仓期间的新 entry 忽略（单仓位口径，报告注明）。
- 退出执行价 = 退出信号次日开盘（保守右侧）；停牌卡壳时顺延到复牌首日开盘并计数。
