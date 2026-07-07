# backtest_platform.md — 回测/研究平台规范

> 对应 ADR-0001。相关任务卡：TASK-025/026（Tier1）、TASK-030（Tier2）、TASK-031/032（Tier3）。

## 1. 三层栈与晋级规则

| Tier | 引擎 | 回答的问题 | 速度 |
|---|---|---|---|
| 1 事件研究 | `quant.research.forward_returns`（纯 pandas/numpy） | 这个信号后 N 天有没有超额？ | 全市场 < 2 分钟 |
| 2 组合回测 | qlib workflow（信号→因子→TopkDropout；M6 接 ML） | 做成组合能不能赚钱？IC 多少？ | 分钟级 |
| 3 交易验证 | Backtrader + A股约束 | 真实规则下能不能成交、净值如何？ | 慢，仅验证候选 |

Tier1 显著 → Tier2 组合仍显著 → Tier3 交易级仍成立 → 才是可用策略。任何一层失败即打回研究。

## 2. Tier1 事件研究语义（必须严格遵守）

- **信号时点**：t 日收盘后由 ≤t 数据算出（indicators 层保证无未来函数）。
- **入场**：t+1 开盘价。**入场过滤**（样本剔除，不是收益修正）：
  - t+1 停牌（`$suspended`）；
  - t+1 开盘即一字涨停（open == limit_up_price，买不进）；
  - t+1 为退市后日期 / 数据缺失。
- **前向收益**（2026-07-07 修订，以 v1 参照实现为准）：horizon h ∈ {1,3,5,10,20}，`ret_h = close(entry_bar + h) / open(entry_bar) - 1`，entry_bar = t+1——**入场日之后再持有 h 个交易日**。本文档旧版写的 entry+h−1 是错的（M2 gate 审查时对照 bt_legacy 源码修正）。
- **输出统计**：样本数、胜率、mean/median/p25/p75、profit factor；支持按年份/市况分组。
- **接口**：
  ```python
  def run_event_study(
      signals: pd.DataFrame,      # index=(symbol,date) 或列[symbol,date]，bool 命中
      horizons: Sequence[int] = (1, 3, 5, 10, 20),
      universe: str = "nostar",
      start: str | None = None, end: str | None = None,
      entry: Literal["next_open"] = "next_open",
  ) -> EventStudyResult            # .per_symbol .pooled .by_year DataFrame + to_report()
  ```
- **CLI**：`myquant study configs/study_kdj_j13.yaml`（配置 schema 见 `configs/study_kdj_j13.yaml` 注释）。

## 3. 费用与约束（单一事实源 `quant/backtest/costs.py`）

| 项 | 默认值 | 说明 |
|---|---|---|
| 佣金 | 万 2.5，最低 5 元 | 双边 |
| 印花税 | 0.05% | 仅卖出（2023-08 起税率；回测更早区间需按期切换 0.1%） |
| 过户费 | 0.001% | 双边，沪市 |
| 滑点 | 0.1%（默认） | 可配 |

A股约束（Tier3 强制，Tier1 以样本过滤形式体现）：
- **T+1**：当日买入不可当日卖出；
- **涨跌停**：主板 ±10%（ST ±5%），创业板/科创板 ±20%，北交所 ±30%；一字板不可成交；
- **停牌**：跳过；
- **最小单位**：100 股整数倍。

## 4. Tier2 qlib 约定

- 实验跟踪：mlflow 本地目录 `DATA_ROOT/mlruns`（不进 git）。
- 基线 workflow（TASK-030）：自有信号因子（`quant.signals.factors`）→ `TopkDropoutStrategy(topk=50, n_drop=5)` → 日频调仓 → 含费用回测；产出年化/IR/换手与 IC 报告。
- 因子输出口径：`signals.factors` 返回 index=(datetime, instrument) 的 float Series（qlib 惯例），布尔信号编码为 {1.0, 0.0} 或连续打分。

## 5. Parity（与 v1 结果对齐——换引擎不许换结论）

- **黄金参照文件**：固化于 `docs/parity/`（来源与口径见其 README）。
- **M2 gate（TASK-025）**：用相同 universe/区间重跑 KDJ J<0 研究，对照 `docs/parity/pipeline_kdj_forward_return_20260311_225334_summary.csv`（另有 5 只样本股小对拍文件）：**样本数完全一致**、胜率差 ≤0.1pp、均值差 ≤5bps。超差必须逐项解释（书面，进 review 文件），禁止静默放宽容差。
- **M3 gate（TASK-032）**：DualTrend bt 策略重跑对照 `docs/parity/dualtrend_breath_full_20260224_220316_summary.csv`，同样本一致性要求。
- v1 引擎口径备忘（M2 审查实证修正）：v1 KDJ 前向收益策略**不做任何停牌/一字板过滤**（过滤逻辑只存在于 DualTrend 策略），且用的是**简单均线 KDJ**（bt.indicators.SMA）而非 TDX 递归——parity 运行必须 `entry_filters: none` + `sma_mode: simple`；生产研究默认 `ashare` 过滤 + TDX KDJ。

## 6. 报告

沿用 `quant.reporting.report`：`<prefix>_summary.csv` + `.md`。研究产物统一写 `backtest_results/`（gitignored），正式对齐报告归档 `docs/reviews/`。
