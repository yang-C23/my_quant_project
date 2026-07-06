# architecture.md — 系统架构

> 决策依据见 `docs/decisions/ADR-0001~0004`。本文描述目标态（M4 完成时）；当前进度看 `docs/roadmap.md`。

## 1. 总览

```
                    ┌────────────────────────────────────────────────┐
   TDX(.day,/mnt/d) │  ETL 层  mirror → parse → staging(Parquet)      │
   GBBQ/blocks      │        → adjust/basics(向量化) → qlib dump_bin  │
   yfinance(美股,M5)│                                                │
   分钟线供应商(预留)└──────────────┬─────────────────────────────────┘
                                   ▼
                    ┌────────────────────────────────────────────────┐
                    │  存储层  /home/yang/quant_data/                 │
                    │   staging/*.parquet   (无损原始+衍生, DuckDB可查)│
                    │   qlib/cn_daily  qlib/us_daily  qlib/cn_1min    │
                    └──────────────┬─────────────────────────────────┘
                                   ▼  quant.data.api (唯一数据入口)
        ┌──────────────────┬──────────────────┬──────────────────────┐
        ▼                  ▼                  ▼                      ▼
  indicators/        research/           backtest/            dashboard/ + pine/
  (TDX公式向量化)    (事件研究+IC)       (qlib workflow +      (FastAPI+LWChars,
  → signals/因子注册  Tier1              Backtrader验证 Tier2/3)  Pine v6 导出)
```

## 2. 模块职责与依赖规则

| 模块 | 职责 | 只准 import |
|---|---|---|
| `quant.config` | pydantic-settings，全部路径/参数来自 `.env` | stdlib |
| `quant.etl.*` | TDX 解析、staging 构建、复权/基础量计算、qlib dump、增量更新、美股采集 | config, pandas/numpy/pyarrow, qlib(dump) |
| `quant.data.*` | `api.get_ohlcv()`、universe 过滤、符号规范化；封装 `qlib.init`+`D.features` | config, qlib, pandas |
| `quant.tdx.functions` | 通达信原语（SMA/EMA/REF/HHV/LLV/CROSS/COUNT/SUM/BARSLAST/IF…）向量化实现，语义 1:1 | numpy/pandas |
| `quant.indicators.*` | 纯函数指标：DataFrame in → DataFrame out，无 IO | **仅** tdx.functions + pandas/numpy |
| `quant.signals.*` | 指标输出 → 布尔信号/因子值的注册表（name → callable） | indicators, data |
| `quant.research.*` | 前向收益事件研究（Tier1）、IC/分层（qlib） | data, signals, reporting |
| `quant.backtest.*` | qlib workflow（Tier2）、bt feed/约束/策略（Tier3）、费用模型 | data, signals, qlib, backtrader |
| `quant.reporting` | CSV/MD 报告输出（沿用 v1） | pandas |
| `quant.dashboard` | FastAPI + 静态前端（Lightweight Charts） | data, signals, research 产物 |
| `quant.pine` | 指标规格 → Pine Script v6 源码 | indicators 的参数元数据 |
| `quant.cli` | typer 入口 `myquant etl|dump|update|validate|study|dash|pine` | 以上各层 |

**依赖方向**：`config ← etl ← data ← {indicators→signals} ← {research, backtest} ← {dashboard, cli}`。
禁止反向 import（如 etl import research）。indicators 层禁止 IO 与 qlib 依赖——这是保证可测试与可 Pine 导出的关键。

## 3. 仓库布局（目标态）

```
AGENTS.md CLAUDE.md pyproject.toml .env.example .pre-commit-config.yaml
.github/workflows/ci.yml
configs/                 # etl.yaml, study_*.yaml, qlib_workflow_*.yaml, bt_*.yaml
src/quant/
  config.py cli.py
  etl/     tdx_parser.py gbbq.py blocks.py mirror.py staging.py adjust.py
           basics.py qlib_dump.py update.py us_yahoo.py
  data/    api.py universe.py symbols.py
  tdx/     functions.py
  indicators/  kdj.py dual_trend.py b1.py amv.py volume_patterns.py
               zhixing_macd.py brick_osc.py
  signals/     registry.py factors.py
  research/    forward_returns.py ic.py
  backtest/    qlib_runner.py bt_feed.py bt_strategies.py bt_constraints.py costs.py
  reporting/   report.py
  dashboard/   app.py api.py static/{index.html,app.js,vendor/}
  pine/        exporter.py templates/
scripts/       validate_vs_pg.py archive_pg.sh      # 一次性运维
tests/         unit/ integration/ fixtures/
docs/          （本目录）
```

## 4. 三层回测栈（详见 backtest_platform.md）

1. **Tier1 向量化事件研究**：信号命中 → t+1 开盘入场 → 1/3/5/10/20 日前向收益分布。全市场一次扫描，秒~分钟级。用于指标筛选与参数扫描。
2. **Tier2 qlib workflow**：信号因子化 → IC/分层 → TopkDropout 组合回测；M6 起接 LightGBM/GPU 模型。用于组合级结论与因子模型。
3. **Tier3 Backtrader 验证器**：qlib provider → bt feed → 现实约束（T+1、涨跌停锁死、停牌、费用滑点）下的交易级复核。用于把 Tier1/2 的候选策略过一遍"能不能真的成交"。

**晋级规则**：Tier1 有效 → Tier2 组合级仍有效 → Tier3 交易级仍有效 → 才算可用策略。

## 5. 遗留代码处置（v1 → v2）

| v1 | 处置 |
|---|---|
| `scripts/tdx_parser.py, gbbq_decoder.py, blocks_parser.py` | `git mv` 入 `src/quant/etl/`（TASK-001），保留算法 |
| `quant/indicators/*.py`（backtrader 版） | 移入 `tests/reference/bt_legacy/` 作黄金值生成参照（TASK-020），M3 后删除 |
| `quant/db/*, scripts/{import_tdx,update_daily,calc_basic,calc_factor}.py` | 只读冻结到 M3（PG 黄金参照期），TASK-033 删除 |
| `quant/backtest/strategies.py` 的约束逻辑 | 提炼进 `bt_constraints.py`（TASK-031） |
| `quant/reporting/report.py` | 保留沿用 |
| 已损坏/未使用（kdj_b1_analysis、BrickIndicator、旧 run_*.py 等） | TASK-004 删除 |
