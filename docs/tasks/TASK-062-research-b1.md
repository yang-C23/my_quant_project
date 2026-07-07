# TASK-062: 研究 — B1 参数族优化（N 形反弹 / 呼吸度组合）

- Milestone: R1　|　State: backlog
- Branch: `task/TASK-062-research-b1`　|　Depends: TASK-060

## Context
docs/indicators/b1.md（三预设 + A1 结构注）。目标是盈亏比（战损比）而非胜率——B1 理论本身就是"低胜率高赔率的左侧低点"。

## Goal
IS 段内找出：哪个版本骨架 + 哪些参数维度真正驱动盈亏比；加 N 形/呼吸度前置条件是否提升。候选 ≤2 组交 OOS。

## Scope
1. **维度筛选先行**（防 200 组合上限爆炸）：先对三预设逐一跑基线，再做单维敏感性（每次只动一个参数：j_max{13,20,26.5}、line_mult{0.985,0.99,0.995}、plry vol 倍数{1.75,1.95,2.15}、three_sum_min{2,3,4}、yangyin 阈值 ±20%），只把敏感维度（h5 均值变化 >15%）进全网格。
2. **组合条件**（作为附加布尔与 sig_b1 相与，各自独立评估）：
   - `+breath_active`（TASK-021 呼吸度）；
   - `+N形`：60 日内存在"低点-反弹≥8%-回撤不破前低"结构（用 tdx.functions 实现一个 `n_shape(df, lookback=60)` 布尔，实现入 `src/quant/indicators/` 并加微用例）；
   - `+双线区间`：yellow < close < white。
3. `objective: profit_factor_h5`（配置显式声明）；密度下限照 PLAN；报告分 regime。
4. `configs/research/b1.yaml` + `docs/research/findings/TASK-062.md`。

## Non-goals
B2/B3 序列策略（另立卡）；市值维度调整（保持 ≥50 亿不动，避免宇宙漂移混入参数效应）。

## Files to touch
`src/quant/indicators/n_shape.py`(新，含测试), `configs/research/b1.yaml`, `tests/unit/test_n_shape.py`, `docs/research/findings/TASK-062.md`。

## Acceptance criteria
1. `pytest -q tests/unit/test_n_shape.py`：合成 N 形/非 N 形序列判定正确（无前视：只用 ≤t 数据）。
2. `myquant research configs/research/b1.yaml` 复现 findings 全部数字（IS 段）。
3. findings 含：三版本基线对照、敏感维度清单、网格 top-5+稳定性、三个组合条件的增量贡献表、候选 ≤2 组。
4. ruff/全套绿；无 2022+ 数字。

## Notes / risks
- B1 信号稀疏（全市场约千次/年级别）——分 regime 后子样本可能不足，报告须给每格样本数并对 n<100 的格标灰。
- warmup >160 根：IS 起点前需预热数据（加载从 2014-04 起，信号从 2015-01-01 起计——runner 需支持 warmup 前置加载，若 060 未覆盖在本卡补）。
