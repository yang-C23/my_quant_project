# TASK-061: 研究 — 活跃市值 0AMV 择时（K 重拟合 / 阈值稳健性 / 右侧确认）

- Milestone: R1　|　State: backlog
- Branch: `task/TASK-061-research-amv`　|　Depends: TASK-060

## Context
docs/indicators/amv_0amv.md；用户明确要做**右侧交易**。AMV 是指数级择时（非横截面），评估方式与个股卡不同：以"regime 内指数收益/回撤"为主指标。

## Goal
IS 段内回答三问：K 系数是否需要重拟合；±4%/−2.3% 阈值是否稳健；哪种右侧确认变体最优。产出 IS 报告 + ≤2 组候选参数供审查者 OOS 裁定。

## Scope
1. `src/quant/research/amv_timing.py`：择时评估器（非事件研究）——对上证指数（sh999999）：
   `evaluate_timing(amv_df, signal_df, index_close) -> TimingStats`：regime=1 期间累计收益、年化、最大回撤、持仓天数占比、切换次数/年、每波段收益分布；对照买入持有与 z哥原版参数基线。
2. **K 系数**：K ∈ {1.8…2.6 步长 0.05} —— K 只影响 AMV 绝对刻度不影响 pct 信号（数学上验证并写进报告：若确认无影响，K 重拟合仅服务于与指南针原版的目视对齐，用最小二乘对 2015–2021 段拟合一个推荐值即可，不做择时优化维度）。
3. **阈值网格**：buy_th ∈ [2.5, 6.0] 步长 0.5；sell_th ∈ [−4.0, −1.5] 步长 0.5（含原版 4/−2.3）；邻域稳定性判据照 PLAN §2。
4. **右侧确认变体**（各作为独立信号列）：
   - `confirm_life`：buy 触发且 `amv_close > amv_life`（生命线上方）才入场；
   - `confirm_2d`：buy 触发后次日 amv_pct > 0 才入场（迟一天，右侧代价量化）；
   - `confirm_break`：buy 触发且指数 close > 近 10 日高点；
   - 原版立即入场作为对照。每变体报告：错过的涨幅（右侧代价）vs 避开的假信号（胜率提升）。
5. `configs/research/amv.yaml` + findings 摘要 `docs/research/findings/TASK-061.md`（IS 结论 + 候选参数 JSON）。

## Non-goals
OOS 评估（审查者）；个股级 AMV；与 B1 联动（进 062 的组合条件或后续卡）。

## Files to touch
`src/quant/research/amv_timing.py`, `configs/research/amv.yaml`, `tests/unit/test_amv_timing.py`, `docs/research/findings/TASK-061.md`。

## Acceptance criteria
1. `pytest -q tests/unit/test_amv_timing.py`：合成 regime 序列的收益/回撤/波段统计手算对齐。
2. `myquant research configs/research/amv.yaml`（或卡内注明的等价命令）在真实数据 IS 段复现 findings 里的全部数字。
3. findings 含：K 无影响性证明（或反证）、阈值热区表、四变体对照表（含右侧代价拆解）、候选 ≤2 组。
4. ruff/全套绿；**不得出现任何 2022+ 日期的数字**。

## Notes / risks
- AMV 波段样本少（IS 约 6 年 × ~10 波段/年）——报告必须给切换次数与每波段收益分布，不许只报均值。
- 指数 amount 单位与缺口防护沿 amv.py 现有实现。
