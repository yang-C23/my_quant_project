# TASK-071: 工程债 — 研究计算层向量化（IC/分层/top-event 热点）

- Milestone: M3（工程债，与 032 返工并行）　|　State: ready
- Branch: `task/TASK-071-research-compute-vectorize`　|　Depends: TASK-067, TASK-068（均已合并）

## Context
TASK-067 把 IO 批量化后 exploratory 全量仍需 ~12 分钟，瓶颈分析（TASK-067-review AC2）定位在
**计算层**：`research/ic.py` 的 rank_ic/quantile_returns 逐日/逐因子 Python 循环、
`forward_returns.py::run_event_study` 的逐事件处理、`exploratory.py::_top_quantile_event`。
本卡只做等价向量化，数值零变化。

## Goal
`myquant research configs/research/exploratory.yaml` 输出 CSV 与现 v2 **逐位一致**，
耗时相对基线（认领时在 v2 实测记录，当前约 12 分钟）**≥2×** 下降；不达标不算失败，
但必须附新的瓶颈分析（哪段仍是热点）。

## Scope
1. 认领后先在 `v2` 跑 `time myquant research configs/research/exploratory.yaml` 记基线耗时，
   并把输出 CSV 存为对照（如 `*_v2-baseline-TASK-071.csv`，放 backtest_results/ 下不入库）。
2. `research/ic.py`：rank_ic / quantile_returns 的逐日循环改 groupby/向量化；
3. `research/forward_returns.py`：`run_event_study` 内逐事件/逐 horizon 循环向量化
   （merge_asof / 索引偏移取代逐行 iloc）；**分桶剔除语义（entry_missing/suspended/limit_up）
   一个都不许变**；
4. `research/exploratory.py::_top_quantile_event`：随 2/3 自然受益，本文件只准适配调用方式；
5. 只改计算实现，不改任何函数签名/返回结构/配置。

## Non-goals
不碰 IO 层（067 已完成）；不改任何研究语义/口径/分桶；不并行化（先向量化）；不碰 OOS；
不动 trade_pairs/optimize。

## Files to touch
`src/quant/research/ic.py`, `src/quant/research/forward_returns.py`,
`src/quant/research/exploratory.py`, `tests/unit/test_ic.py`, `tests/unit/test_forward_returns.py`,
`tests/unit/test_exploratory_factors.py`（如口径需适配——预期不需要，改了要说明）

## Acceptance criteria
1. 结果不变性：任务分支重跑 `myquant research configs/research/exploratory.yaml`，CSV 与
   步骤 1 的 v2 基线 **`diff` 逐位一致**。
2. 性能：两个耗时数字（v2 基线 / 分支）写入 STATUS 备注，目标 ≥2×；不达标附瓶颈分析。
3. `pytest -q -m "not integration"` 全绿且**既有断言零改动**（现有单测就是语义锁）。
4. `ruff check .` + `ruff format --check .` 全绿。

## 验收如何被作弊/退化满足？

1. **跳算换速度**：少算列/少算因子能"提速"——AC1 的 CSV 逐位一致是总闸，任何列缺失/数值漂移
   直接红。
2. **基线造假**：v2 基线耗时虚报高、或基线 CSV 用分支跑——审查者将亲自在 v2 与分支各跑一次
   全量对照（同 067 审查模式，三方逐位比）。
3. **改断言凑绿**：既有单测断言即语义规格，AC3 明令零改动；diff 中出现断言修改=打回。
4. **浮点路径漂移**：向量化把逐点除法改成矩阵运算可能引入不同的求和顺序——凡引入
   `np.sum`/`groupby.mean` 等聚合顺序变化处，以 AC1 逐位一致为准，对不齐就换保序实现，
   不许用"容差比较"替代 diff。
5. **计时口径**：冷/热缓存混比——两侧都用同机顺序单次 `time` 全量口径。

## Test plan
既有单测即回归锁；AC1 全量逐位对照为集成级验证。

## Notes / risks
- rank_ic 的 spearman 逐日循环是最大头；pandas `groupby().rank()` + 向量相关系数可保逐位
  （rank 后 pearson ≡ spearman，注意 tie 处理与 scipy 默认一致性——对不齐时保留逐日路径仅
  向量化外层）。
- run_event_study 的事件对齐用 (symbol,date)→position 映射向量化时注意 horizon 越界事件的
  `*_missing` 分桶与现实现逐个一致。
