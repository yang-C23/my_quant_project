# R1 批次一审查（TASK-060 ~ TASK-065）

- 审查者：Claude（规划/审查代理）
- 日期：2026-07-07
- 被审分支：`task/TASK-060-research-infra` (df860e7) → … → `task/TASK-065-research-exploratory` (e86081c)，线性堆叠
- 裁定：**六卡代码全部合并**；但 062/063/064/065 首轮扫描结果**作废重跑**（原因见 F-1），
  审查者修复后以本文档所附重跑结果为准。findings 文档随重跑同步改写。

## 验收复核

- `pytest -q tests/unit`：合并前 166 passed（Codex 自述属实）；审查者修复后 168 passed。
- `ruff check src tests/unit`：通过。
- 冻结引擎核查：`forward_returns.py` 未被触碰；`ic.py` 仅新增空表守卫（安全）；
  `b1.py` 仅参数化 `plry_mult`（默认 1.95 = 原常量，M2 黄金 parity 不受影响，回归测试全绿）。
- IS 红线扫描：新增文件无 2022+ 日期；`_reject_post_is_dates` / `_validate_is_window` 实测拒绝越界配置（单测覆盖）。
- 无前视核查：n_shape 有构造性"未来 bar 不改历史"测试；AMV regime 统一 `shift(1)` 生效；
  trade_pairs 入场/出场均为信号次日开盘。

## 审查发现（按严重度）

### F-1 🔴 采样偏差：`max_symbols: 300` 头部截断 = 全北交所样本（062/063/064/065）
`list_symbols` 按符号字典序返回，`bj*` 排最前；`symbols[:300]` 取到的 300 只**全部是北交所股票**
（bj430017…bj920069）。北交所 2021-11 开市（精选层 2020-07），IS 窗口 2015–2021 内几乎无数据：
b1 七年最多 240 个信号、dual_trend 矩阵最少 70 笔、exploratory 日均截面仅 ~50 只。
四卡首轮结论全部建立在废样本上，**一律作废**。

**修复**：`optimize.sample_symbols()`（种子化均匀抽样，默认 seed=42），三个入口
（optimize/_resolve_symbols、trade_pairs 两 runner 及 gem 对照路径、exploratory）统一接入；
四个 yaml 改为 `max_symbols: 800 + sample_seed: 42`。附确定性+跨交易所混合单测。
**根因归属**：TASK-060 卡面未规定采样方式，规划者卡面漏洞；Codex 在 findings 里如实披露了
"first 300 symbols"，无隐瞒。

### F-2 🔴 `stop_loss="entry_low"` 退化：止损在入场日恒真（064）
止损价=入场日最低价，检查从入场日开始且用 `<=`：`low(entry) <= low(entry)` 恒真 →
50 个 entry_low 网格点全部 `avg_hold_days=1.0`，等价于"次日开盘卖出"。
笔记里砖形的核心规则"跌破买入 bar 低点止损"**从未被真实测试**，
且 `test_entry_low_stop_and_two_day_no_profit` 把该行为固化成了断言。

**修复**：entry_low 改严格 `<`（"跌破"语义；数值止损保留 `<=`，入场日盘中触及合法）；
重写测试 + 新增"入场日不得自触发"用例。064 前次 top-2 候选用的是数值止损 0.03，不在污染行内，
但整个矩阵需随 F-1 一并重跑。

### F-3 🟡 turnover 因子假阴性（065）
`turnover` 字段在 qlib dump 清单里且数据完好，但 `_compute_one_factor` 用默认字段加载
（不含 turnover）→ `turnover_weighted_cost` 两行 `mean_n=0`，报表呈现为"测了无效"，
实为"从未计算"。**修复**：`_FACTOR_FIELDS` 显式含 turnover。

### F-4 🟡 探索因子单调性判定只认正向（065）
`quantile_spearman.ge(0.8)` 会误杀负向单调因子（反向使用同样可交易）。
**修复**：改 `.abs().ge(0.8)`，方向由 ic_mean 符号读出。

### F-5 🟡 b1 的 case 网格使 stable_neighborhood 列失义（062）
`case` 是人工挑选的 26 条组合列表，±1 步"邻居"=列表相邻项，参数语义上不是邻域。
该列在 b1 报告中不可采信；b1 的稳健性证据以单维敏感性读数为准。
本轮 b1 无正收益候选，不影响结论；若未来 b1 出现候选，需改用结构化网格重验稳定性。
（不改代码，记录为基础设施已知限制。）

### F-6 🟡 n_shape O(n·L²) 纯 Python 循环不可扩展（062）
Codex 版在北交所废样本（~300 bar 历史）上恰好跑得动；真实样本 1700 bar × 800 只 ×
4 个 n_shape case 需数小时（实测跑 28 分钟无产出后被审查者终止）。
**修复**：等价向量化（`np.fmin.accumulate` 前后缀最小值，保 pandas nanmin 语义），
1700 bar 从分钟级降至 12ms；20 组随机对拍（含 NaN/零价注入）与原实现逐位一致，
原构造性测试原样通过。

### F-7 🟢 其他记录
- `myquant research` 的 `--oos-final` 路径为占位拒绝（by design）：OOS 由审查者以独立脚本执行（TASK-066）。
- trade_pairs 的 MAE/MFE 统计到出场信号日为止，停牌顺延期间的风险未计入（低估尾部 MAE，已知口径）。
- IS 末端持仓被强制在数据窗口末平仓（截断而非剔除），对 max_hold=120 的双线交易有轻度截尾效应。
- `_signal_true_on` 逐 bar 过滤为 O(n²)，800 样本可用；未来批量化与 study 性能债合并处理。
- cli.py 无 `__main__` 守卫，`python -m quant.cli` 静默空跑——审查者以 `myquant` 入口执行；
  守卫补充留给后续工程卡（非本批范围）。

## 061（AMV）审查专项

样本为单指数 sh999999，不受 F-1 影响，首轮结果有效。两点审查者补充：

1. **结构性候选**（进入 OOS 名单）：原版 z哥阈值不动、仅加 confirm_life 右侧确认
   （`k=2.13, buy=4.0, sell=-2.3, variant=confirm_life`）：
   IS 累计 0.595 vs immediate 0.310，最大回撤 −0.189 vs −0.335，PF 2.21 vs 1.49，
   切换次数更少。零调参 → 过拟合面最小，符合用户右侧交易诉求。
2. **网格边界**：top-5 全落在 sell_th=−1.5 边界且各变体沿 sell_th 单调向好 →
   审查者把 sell 网格扩展到 −1.0/−0.5 重跑探顶（见重跑结果）。

## 重跑结果（审查者修复后，800 样本 seed=42）

数字以各 findings 修订版为准，此处只记结论级变化：

| 卡 | 首轮（废样本）结论 | 修复重跑结论 |
|---|---|---|
| 061 AMV | top-5 全在 sell=−1.5 边界、无候选 | sell=−1.0 内部极值；调参点按邻域判据弃用；**结构性候选 confirm_life@原版阈值入 OOS**（IS 累计 0.595 vs 0.310） |
| 062 B1 | 无正收益密度合格候选（240 信号） | **原版基线费前负期望**（3568 信号、PF 0.971）；25/26 行 PF<1；唯一正行 dual_zone（PF 1.07、笔均 +0.19%）因 F-5/费用/单点极值不立候选；无候选 |
| 063 双线 | dead_cross 候选 PF 3.55（84 笔） | **候选蒸发**：5250 笔下 PF 1.15、笔均 +0.93%、中位 −4.4%；无退出规则击败原版死叉；无候选 |
| 064 短线 | single_needle hold4/stop3% PF 3.59（45 笔） | **候选蒸发**：405 笔下该组合 PF 0.96；全部边际集中在 hold=1（PF 1.18，CI 含 1.0）；笔记先验 37%/3:1 不成立；无候选 |
| 065 探索 | 全部无效（截面 ~50 只，turnover 假阴性） | 全部仍未过门槛，但 washout_area_ratio（ICIR +0.257，完美正单调）与 turnover_weighted_cost（−0.257，完美负单调）留档 M6 |

运行时长（修复后）：amv 4s、exploratory 15m、dual_trend 6m、shortterm 8m、
b1 后台完成（n_shape 向量化后；首轮 O(n·L²) 版 28 分钟无产出被终止）。
exploratory/dual/short 的主耗时是逐符号
qlib IO——与既有 study 性能债同源，记入工程债一并批量化。
