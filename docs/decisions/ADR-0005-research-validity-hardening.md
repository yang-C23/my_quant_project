# ADR-0005: 研究有效性加固（M3.5 立项）、PG 退役门槛收紧、数值验证分级

- 状态：accepted
- 日期：2026-07-10
- 决策人：用户（确认 M3.5 立项与全部裁定）+ 规划者

## Context（背景与约束）

一份外部架构 review 对研究平台提出系统性指控，规划者逐条独立复核（代码定位 + 合成数据实测），
13 条硬指控 12 条属实：

1. **标签错位**：同 h，事件研究 `exit_pos = entry_pos + horizon`（`forward_returns.py`）vs IC
   `exit_pos = entry_pos + horizon - 1`（`ic.py`）——合成序列实测 h=5 差一个 bar
   （0.054726 vs 0.044776）；且 IC 路径无停牌/一字涨停入场过滤。
2. **抽样不稳定**：`sample_symbols` 按整数位置 `rng.choice`——universe 5465→5466 插 1 只，
   实测 800 样本被换掉 368 只（R1 勘误 3 的 turnover_cost w60 翻案即此机制）。
3. **朴素推断**：重叠 forward return 的 IC t 统计假定 iid（`mean/(std/√n)`）；事件池化无
   日期/证券聚类；bootstrap 按单笔交易重采样，低估共同市场冲击。
4. **伪净值**：`quantile_returns.cum_return` 为重叠收益 cumsum；qlib risk 指标为加和口径
   （030 review：mdd −116% 物理不可能，已记档）。
5. **OOS 消费**：2022–2024 已被 R1 一次性裁定消费，对 R1 各信号族不再是未见 OOS。
6. **方向处理**：探索因子 abs(ICIR) 门槛 + 固定 top 20% 事件——负向因子的 top 侧恰为预期弱侧。
7. **邻域判据**：`≥0.7×best` 对负值/跨零指标语义不成立（F-5 的补充）。
8. **退出语义不对称**：`trade_pairs` 仅 `stop_loss` 出场受跌停约束，信号/max_hold 出场可在
   一字跌停开盘"成交"；MAE/MFE 截断于出场信号日（F-7 已知）。
9. **滑点**：固定比例常数，无流动性/参与率维度。

R1 零候选结论有预声明 OOS 一次性裁定兜底，上述缺陷不足以翻转其任何否决结论——**R1 不重开**。
但在这些缺陷修复前，任何新的因子晋级、策略搜索与 M6 ML 研究的"发现"都不可信。

## Decision（决定）

1. **立项 M3.5 — Research Validity Hardening**，位于 M3 之后；M4（看板）可与之并行；
   **M6 的任何因子/ML 晋级以 M3.5 gate 为前置**。
2. **研究语义统一**：单一 `LabelSpec`（signal=close_t → entry=open_t+1 → exit=close(entry+h)，
   "after_entry" 计数，ashare 入场过滤，qfq）为事件研究与 IC 的共同口径事实源；一切研究
   产物带 spec hash。prediction return（mark-to-market，供 IC/模型标签）与 executable return
   （含费用/延期/部分成交，供晋级）分离，后者 M3.5 二批实现。
3. **抽样**：改与 universe 顺序/长度无关的稳定哈希抽样（乱序不变、±1 只最多换 1 个成员）；
   正式晋级研究默认全 universe，抽样仅限单测/冒烟/早期探索（071 向量化 ≥7× 已使全 universe
   Tier1 可行）。
4. **统计推断**：重叠标签用 HAC（lag ≥ 最大 horizon）/ block bootstrap / date×symbol 聚类；
   全部参数与方向尝试进 append-only trial ledger；建 holdout 访问台账（2025+ 是否干净按
   "假设 × 台账"判定，不按日期一刀切）；因子筛选 FDR、参数族 PBO/CSCV、策略 DSR。
   **具体门槛数值在 R2 协议冻结时按样本长度校准，冻结后不许改**（研究中途调门槛=红线）。
5. **因子方向预声明**：`FactorSpec.expected_direction` 研究前声明，signed 评估
   （负向因子 long 侧=低原始值）；方向未知时双向各计一次试验入账，禁止事后看 IC 翻方向。
6. **组合口径**：canonical 复利净值（`(1+r).cumprod()`、传统 MDD）与 qlib 加和口径并行输出、
   显式命名；禁止 overlapping forward return cumsum 冒充净值。
7. **执行语义**：研究引擎全部卖出原因统一受跌停/停牌约束（与 Tier3 对齐）；滑点升级为
   流动性/波动率/参与率敏感模型（M3.5 二批）。
8. **PG 退役门槛收紧（修订 ADR-0002 安全网条款）**：TASK-033 前置增加
   (a) 不可变快照 manifest——staging/qlib/黄金 CSV/PG dump/环境/commit 全链 SHA256，
   freeze/verify 工具化；(b) 恢复演练——在无 pg_quant 容器的环境从 dump 恢复并复跑
   016/025/032 黄金验证。演练未过不许删码。
9. **数值验证三级制**，任务卡置 ready 前必须预声明类别：
   - **Class A 逐位一致**：legacy parity、费用/会计、符号转换、数据 dump、黄金复现；
   - **Class B 数值等价**：并行聚合/向量化统计——卡面预声明 atol/rtol/ULP 上限与 NaN 语义；
   - **Class C 统计等价**：ML/bootstrap/随机优化——比较分布、CI、方向与经济结论。
   （TASK-071 的教训：该 Class B 的活被默认成 Class A，返工一轮——此后由卡面预声明消除。）
10. **R2 研究方向裁定**：turnover_weighted_cost 预声明 negative、全 universe 首发（R2 首要
    线索，非已确认候选）；DualTrend/B1 降为连续趋势状态/条件特征，验收看对基础因子的
    **增量**（IC/净 active return/换手/回撤四维）；AMV 只作组合风险 overlay，须与固定仓位、
    均线 regime、波动率目标、市场宽度基线公平对比（同均仓/同波动口径）；模型复杂度阶梯
    signed rank → 线性 → ridge/elastic net → 浅 LightGBM，逐层同协议增量晋级。
11. **不采纳/推迟**：shadow trading / monitoring 推迟至 R2 产出候选后（YAGNI）；不做预先的
    research 模块大重组（模块按卡需要生长）；R1 不重开、不为翻案挖参数。

## Consequences（后果）

- 得到：统计可信度、样本稳定性、可交易解释成为平台能力而非逐卡自觉；PG 退役这一不可逆
  操作获得恢复演练兜底；数值验收分级终结"B 类活按 A 类判"的返工。
- 放弃：R1 存档数字与新语义不再可比（findings/reviews 冻结不重跑，M6/R2 全用新口径）；
  alpha 产出时间表后移一个里程碑。
- 风险：M3.5 工程化拖长研究节奏——以 M4 并行、R2 方向预研已完成对冲；对抗式验收增加
  卡面成本——规格期抓比实现期便宜一个数量级（F-1/F-2/F-3 的教训）。

## Alternatives considered（被否掉的方案）

- **直接进 M6 用 ML 找 alpha**：标签错位与选择偏差未修，任何"发现"不可信——否。
- **全盘照单外部 review**（11 个新模块 + shadow monitor 立即建）：违反 YAGNI 与单卡 ≤1 天
  合同；能力全收、架子按需生长——部分采纳。
- **为 turnover_cost 翻案重开 R1**：其 effective 翻转恰是抽样不稳定的产物，先修平台再
  全 universe 正式检验（R2）——否。
