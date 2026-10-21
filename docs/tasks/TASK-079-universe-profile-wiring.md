# TASK-079: UniverseProfile 接线 — 研究/回测入口统一吃 EligibilityPanel

- Milestone: M3.5　|　State: backlog（Depends: TASK-078 + TASK-071/074/075 合并——
  白名单与 071/075 在途分支同碰 optimize/exploratory，由规划者在依赖全合后置 ready）
- Branch: `task/TASK-079-universe-profile-wiring`　|　Depends: TASK-078, 071, 074, 075

## Context
TASK-078 交付面板与两档 profile 后，研究与回测入口仍各自 `list_symbols(at=None)` +
自行过滤。本卡把横截面资格统一接到 EligibilityPanel：**因子横截面/IC/Topk 的每日成员
由 profile 决定**，报告带 profile hash（ADR-0005 §3 "正式研究默认全 universe" 中的
"universe" 自此指 profile 过滤后的日度合格集）。

## Goal
`configs/research/*.yaml` 与 `configs/backtest/*.yaml` 可声明 `universe_profile:
eligible_research_v1|eligible_tradable_v1|none`；研究扫描、探索因子、qlib Topk 三个入口
的日度横截面按面板过滤；输出报告头部含 profile 名 + hash；`none` 保持现行为（回归口径）。

## Scope
1. `research/optimize.py` / `research/exploratory.py`：配置增 `universe_profile` 键
   （默认 `none`=现行为）；signals/factor 帧在进入事件研究/IC 前按
   `eligible_mask` 过滤（t 日不合格 → 当日该股不入横截面）；
2. `backtest/qlib_topk.py`：UniverseConfig 增 profile 字段，score series 按日度 mask
   过滤（不合格日的 score 置 NaN/剔除）；
3. 三个入口的 md/CSV 报告与 mlflow params 记录 `universe_profile` 名 + hash；
4. 单测：小 fixture 上 `none` 与显式 profile 的输出差异 = 手算被剔除样本集。

## Non-goals
不改 Tier1/Tier3 入场执行过滤（entry_filters=ashare 语义不动——资格过滤是横截面成员
问题，执行过滤是成交可行性问题，两层各管各）；不回填 R1 存档。

## Files to touch
- `src/quant/research/optimize.py`
- `src/quant/research/exploratory.py`
- `src/quant/backtest/qlib_topk.py`
- `configs/research/_TEMPLATE.yaml`
- `tests/unit/test_optimize.py`
- `tests/unit/test_exploratory_factors.py`
- `tests/unit/test_qlib_topk.py`

## Acceptance criteria
（置 ready 时由规划者按届时代码状态复核细化）
1. `universe_profile: none` 下三个入口输出与改动前**逐位一致**（回归锁）；
2. fixture：显式 profile 下被剔除的 (date,symbol) 恰为手算不合格集，且报告头含
   profile hash；
3. 真实数据冒烟：exploratory 以 `eligible_research_v1` 全量跑通，横截面日均样本数
   写 STATUS（应明显小于全宇宙 5466）；
4. 质量门全绿。

## 验收如何被作弊/退化满足？
1. **过滤只改报告头不改数据**：AC2 剔除集逐格断言；AC3 日均样本数必须下降。
2. **`none` 路径顺手漂移**：AC1 逐位回归锁。
3. **在信号层而非横截面层过滤**（等价但语义错位，Topk 侧会漏）：AC2 在 IC 与 Topk
   两侧分别断言。

## 数值验证类别与变形测试
Class A（`none` 逐位回归 + fixture 手算剔除集）。变形：对合格股集合加一只不合格股，
输出不变。

## Test plan
三入口各一组 fixture 单测 + 真实数据冒烟（AC3）。

## Notes / risks
- 依赖 071/074/075 全部合并后才能置 ready（文件冲突 + IC 语义先统一）；届时规划者
  按新代码复核签名与 AC。
