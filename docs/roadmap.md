# roadmap.md — 里程碑与通过门槛

> 优先级来自用户需求：① 数据+回测平台 → ② 用已有指标验证回测系统 → ③ TradingView 可视化 → ④ 先A股后美股。
> 每个里程碑的 gate 由规划者亲自运行验证，报告存 `docs/reviews/M?-gate-report.md`，通过后打 tag `v2.0-m?`。

## M0 — 脚手架（卡：TASK-001 ~ 004）

| 卡 | 内容 |
|---|---|
| TASK-001 | src 布局迁移 + pyproject.toml（锁版依赖）+ ruff/pytest/pre-commit |
| TASK-002 | GitHub Actions CI（lint + 单测 + qlib 导入冒烟） |
| TASK-003 | `quant.config` 设置模块 + `.env.example`，清除全部硬编码路径 |
| TASK-004 | 死代码/死依赖清理 |

**Gate M0**：全新克隆 → `pip install -e ".[dev]"` → `pytest -q -m "not integration"` + `ruff check .` 全绿（本地与 CI）；`python -c "import qlib, quant"` 成功。

## M1 — 数据平台（卡：TASK-010 ~ 016）｜优先级①

| 卡 | 内容 |
|---|---|
| TASK-010 | 镜像 + 并行 .day 解析 → staging daily Parquet（`myquant etl full` 骨架） |
| TASK-011 | GBBQ/securities/blocks/holidays/ST/停牌/涨跌停 → staging |
| TASK-012 | 向量化复权因子（hfq/qfq）→ staging/adjust |
| TASK-013 | qlib dump（calendars/instruments/features）`myquant dump cn-daily` |
| TASK-014 | `quant.data.api` + universe + symbols |
| TASK-015 | 增量日更 `myquant update`（tail-read，幂等） |
| TASK-016 | `scripts/validate_vs_pg.py` 黄金对齐报告 |

**Gate M1**：全量导入（镜像+解析+衍生+dump）≤ ~15 分钟；`D.features(["SH600000"],["$close","$factor"])` 对齐 PG `v_hfq_daily` 黄金值；validate 报告 0 硬失败（原始 OHLCV 全等、hfq ≤1e-6、日历/行数/区间一致，qfq 仅宽松带 warning，见 data_platform.md §6）；模拟一次日增量后重跑 validate 仍通过，且 `myquant update` 连跑两次第二次为无操作。

## M2 — 指标 + 研究引擎（卡：TASK-020 ~ 026）｜优先级②

| 卡 | 内容 |
|---|---|
| TASK-020 | `quant.tdx.functions`（黄金 CSV 来自 v1 backtrader 实现） |
| TASK-021 | KDJ（TDX 变体）+ 双线 V2.1（含呼吸度） |
| TASK-022 | B1 三版本（v2.42b / v2.42p / v2.42.62） |
| TASK-023 | 活跃市值 0AMV（指数级）+ ±4%/-2.3% 择时信号 |
| TASK-024 | 倍量柱/单针下20(代理版)/知行MACD/砖形振荡器 |
| TASK-025 | 前向收益事件研究引擎 + `myquant study` |
| TASK-026 | qlib IC/分层分析封装 |

**Gate M2**：TASK-025 重跑历史 KDJ J<0 研究（同 universe/区间）对照 `docs/parity/pipeline_kdj_forward_return_*.csv`：样本数完全一致、胜率 ±0.1pp、均值 ±5bps；全市场运行 < 2 分钟。全部指标黄金值测试通过。

## M3 — 回测平台 + PG 退役（卡：TASK-030 ~ 033，届时补卡）

030 qlib TopkDropout 基线 + mlflow ｜ 031 bt_feed + bt_constraints（T+1/涨跌停锁死/停牌回归测试）｜ 032 DualTrend bt 复现历史 `dualtrend_breath_*` 报告 ｜ 073 快照冻结 manifest + PG 归档 dump（033 前置，ADR-0005 §8）｜ 033 PG 归档退役 → 删除 db 代码/旧脚本、停容器（ADR-0002 标记 executed）。

**Gate M3**：016/025/032 三份对齐报告全绿 + TASK-073 manifest freeze/verify 通过 + **恢复演练**（规划者在无 pg_quant 容器环境从 dump 恢复并复跑 016/025/032 黄金验证，ADR-0005 §8）**之后** 才允许合并 033；此后 `grep -r psycopg2 src/` 为空，停掉 pg_quant 容器全测试仍绿。

## M3.5 — Research Validity Hardening（卡：TASK-074 ~ 076 + 二批届时补卡）

研究有效性加固（立项依据与全部裁定见 ADR-0005）。M4 可与之并行；**M6 被本 gate 阻塞**。

| 批次 | 卡 | 内容 |
|---|---|---|
| 一批 | TASK-074 | 研究语义契约 LabelSpec：Tier1/IC 标签统一（消 off-by-one、IC 补 ashare 过滤、spec hash 进报告） |
| 一批 | TASK-075 | 稳定哈希抽样（乱序不变、universe ±1 最多换 1 个成员、均匀性反截断） |
| 一批 | TASK-076 | trade_pairs 退出语义统一（全部卖出受跌停/停牌约束 + MAE/MFE 顺延窗口） |
| 二批 | 届时补卡 | 日度 PIT EligibilityPanel；HAC/block bootstrap/聚类推断；trial ledger + holdout 访问台账；signed factor evaluator；FDR/DSR/PBO 报告；canonical 复利净值；executable return（费用/延期/部分成交）；成本容量与冲击；benchmark suite |

**Gate M3.5**（详见 ADR-0005 §2–§7；通过后才开 R2 正式研究与 M6 晋级类卡）：
① 事件研究/IC/未来 ML 标签引用同一 LabelSpec 且报告带 spec hash；② 抽样变形测试全过，
正式研究默认全 universe；③ 重叠推断工具（HAC/block bootstrap）与参考实现对拍一致；
④ trial ledger 与 holdout 台账运转（全部试验入账、OOS 消费自动标记）；⑤ 对抗验收：
合成随机无 alpha 因子集的晋级率 ≈ 预声明一类错误率。

## M4 — 看板 + Pine（卡：TASK-040 ~ 043，届时补卡）｜优先级③

040 FastAPI JSON API ｜ 041 LWC 前端（K线/叠加/副图/marker）｜ 042 回测 run 叠加（权益/交易）｜ 043 Pine v6 导出器（kdj/dual_trend/b1）。

**Gate M4**：`myquant dash` 展示 sz000001 + KDJ 副图 + B1 marker，数值与 `quant.data.api` 一致（API 自动化测试 + Playwright 冒烟）；一份导出 .pine 粘贴 TradingView 抽样日期信号吻合（±1 bar 记录在案）。

## M5 — 美股 + 分钟线预留（卡：TASK-050 ~ 051，届时补卡）｜优先级④

050 yfinance → us_daily region ｜ 051 分钟线契约干跑（合成 CSV → staging/min1 → cn_1min）。

**Gate M5**：us region `D.features` 可用；1min 干跑全流程通过（此后才允许花钱买分钟数据）。

## M6 — 因子模型 / ML（届时补卡）

指标→因子数据集 handler、LightGBM 基线（GPU 可选）、walk-forward 验证协议、IC 报告体系。与 qlib Alpha158 对比基线。
**前置：M3.5 gate 通过（ADR-0005）**；模型复杂度阶梯 signed rank → 线性 → 正则 → 浅 LightGBM，逐层同协议增量晋级。

**Gate M6**：walk-forward 报告 + 规划者走查（无泄漏、无过拟合红旗）+ ADR-0005 统计/经济/执行门（trial ledger 完整、FDR/DSR/PBO 达预冻结门槛、成本后 active return、容量分析）。

## R1 — 指标优化研究（与 M3/M4 并行的研究轨道）

协议与逐指标方向见 `docs/research/PLAN.md`；卡片 TASK-060（基础设施）→ 061~065（并行研究）→ 066（规划者 OOS 裁定 + `v2.0-r1`）。硬约束：开发代理只准触碰 IS 段（2015–2021），OOS 由审查者一次性裁定，2025+ 封存。采纳的候选进入 Tier3 验证队列（M3 后执行）。
