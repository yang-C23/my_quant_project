# TASK-065: 探索研究 — 底部红绿量占比（算面积）/ 筹码分布代理

- Milestone: R1　|　State: backlog
- Branch: `task/TASK-065-research-exploratory`　|　Depends: TASK-060

## Context
volume_patterns.md 的"算面积"震仓判别（`washout_area_ratio` 已有连续值实现）与笔记中的筹码分布思路（天眼 v1.0 的 CHIP_SPREAD 残片、指南针筹码不可得）。**探索卡：先验证有效性，有效才立优化卡**——本卡允许全负结论。

## Goal
回答一个问题：这两类构造在 IS 段是否有统计学上站得住的预测力（IC 显著 ≠ 0 且分层单调）。

## Scope
1. **红绿量占比因子族**（连续值，`src/quant/signals/factors.py` 注册为 factor）：
   - `washout_area_ratio`（现有，窗口 {20,40,60}）；
   - `red_green_vol_ratio`：近 N 日阳量和/阴量和（B1 的 YANGYIN 构件连续化，N ∈ {14,28,57}）；
   - `bottom_area_score`：价格处于 120 日低位 30% 分位 × washout_area_ratio（"底部"限定）。
2. **筹码分布代理**（日线可计算的近似，明示局限）：
   - `turnover_weighted_cost`：近 N 日换手加权均价偏离 `(close/加权成本−1)`（N ∈ {30,60}）；
   - `chip_concentration`：近 60 日成交额加权价格标准差/均值（集中度低=筹码密集）。
3. 评估：`myquant ic` 全套（RankIC/ICIR/衰减/5 分位单调/日样本数）+ 对每因子取 top 分位做 Tier1 事件研究抽查；regime 分层。
4. **判定标准（写死）**：|ICIR| ≥ 0.3 且分层单调（Spearman(分位序,收益序) ≥ 0.8）→ "有效，建议立优化卡"；否则"无效/存疑"如实归档。
5. `docs/research/findings/TASK-065.md`。

## Non-goals
参数优化（本卡只验证）；分钟级筹码模型（数据未购）；指南针原版复刻。

## Files to touch
`src/quant/signals/factors.py`(新增因子注册), `tests/unit/test_exploratory_factors.py`, `configs/research/exploratory.yaml`, `docs/research/findings/TASK-065.md`。

## Acceptance criteria
1. `pytest -q tests/unit/test_exploratory_factors.py`：每因子无前视（构造性测试：扰动 t+1 数据不改变 t 因子值）+ 手算微用例。
2. 复现命令跑通；findings 按判定标准给出每因子结论表。
3. ruff/全套绿；无 2022+ 数字。

## Notes / risks
换手率因子对退市/低流通股本敏感——turnover 缺失/为 0 的行剔除并计数；结论若"无效"同样有价值（防止后续在弱因子上浪费优化预算）。
