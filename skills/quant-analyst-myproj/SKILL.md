---
name: quant-analyst-myproj
description: Quant analyst skill for my_quant_project. v2 (branch v2) is a qlib-primary platform with Parquet staging and a dual-agent dev workflow (Claude plans/reviews, Codex implements via docs/tasks); v1 sections remain as legacy reference while PostgreSQL serves as golden reference until M3.
---

# Quant Analyst (My Quant Project)

## ⚠️ v2 重构进行中（先读这段）

自 2026-07-06 起项目在 `v2` 分支上按新架构重构（`main` = v1 冻结态）：

- **架构**：TDX → Parquet staging → **qlib bin**（唯一研究存储）；qlib 为主引擎 + Backtrader 交易级验证；FastAPI + Lightweight Charts 看板 + Pine 导出。决策见 `docs/decisions/ADR-0001~0004`。
- **双代理工作流**：Claude 规划/审查（`CLAUDE.md`），Codex 按任务卡开发（`AGENTS.md`）；看板 `docs/tasks/STATUS.md`；流程 `docs/workflow.md`。
- **v2 命令入口**：`myquant etl|dump|update|validate|study|dash|pine`（逐里程碑落地，见 `docs/roadmap.md`）。
- **PostgreSQL 状态**：已冻结写入，仅作黄金参照（`scripts/validate_vs_pg.py`）到 M3 gate，之后归档删除。**下方 v1 的 DB/脚本命令仅用于参照与对拍，不再用于日常数据更新。**
- 指标公式与移植规范：`docs/indicators/`；黄金 parity 报告：`docs/parity/`。

——以下为 v1 遗留手册（在 `main` 分支与 PG 参照场景下仍有效）——

## Purpose
Expert in quantitative finance, algorithmic trading strategies, and financial data analysis, specialized for the `my_quant_project` codebase. Provides rigorous backtesting, risk-aware analytics, and clean engineering practices using the Python scientific stack, Backtrader, PostgreSQL, and disciplined GitHub version control.

## When to Use
- Build or extend A-share backtests in `my_quant_project`
- Add indicators, signals, or strategy logic
- Import, update, or query TDX market data in PostgreSQL
- Run or automate data updates and reporting
- Refactor the pipeline or config-driven workflows
- Design research metrics or validation protocols
- Manage project updates with GitHub checkpoints, rollback-friendly workflow, and synchronized local skills

## Quick Start (Project Commands)
```bash
# Activate environment and enter project
eval "$(/home/yang/venvs/miniconda3/bin/conda shell.bash hook)"
conda activate /home/yang/venvs/my_quant_env
cd /home/yang/projects/my_quant_project

# Confirm repo state before starting work
git status --short
git branch --show-current
git log --oneline -5

# -- Database operations --

# Start PostgreSQL (Docker)
docker start pg_quant

# Full import from TDX (first time only)
python scripts/import_tdx.py --zip /mnt/d/TDX_hsjday.zip --tdxhome /mnt/d/new_tdx

# Daily incremental update (after TDX downloads latest data)
python scripts/update_daily.py --vipdoc /mnt/d/new_tdx/vipdoc --tdxhome /mnt/d/new_tdx

# -- Backtesting --

# KDJ J<0 forward-return backtest (loads from DB)
python run_backtest.py --start 2015-01-01 --end 2024-12-31

# Config-driven pipeline
python run_pipeline.py --config configs/pipeline_kdj_j0.yaml
```

## Repository Context (Key Modules)
```
my_quant_project/
├── configs/                     # Pipeline configs
├── backtest_results/            # Backtest reports
├── quant/
│   ├── backtest/engine.py        # Backtrader entrypoints (DB)
│   ├── backtest/strategies.py    # KDJ, DualTrend strategies
│   ├── data/loader.py            # DB loader + symbol resolution
│   ├── db/connection.py          # PostgreSQL connection manager
│   ├── db/schema.py              # DDL: tables, indexes, views
│   ├── indicators/               # KDJ, DualTrend, VolBreath, Brick
│   ├── reporting/report.py       # CSV/MD report generation
│   └── pipeline.py               # Config-driven pipeline
├── scripts/
│   ├── import_tdx.py             # Full TDX -> PostgreSQL import
│   ├── update_daily.py           # Incremental daily update
│   ├── tdx_parser.py             # TDX binary .day parser
│   ├── gbbq_decoder.py           # GBBQ decryption
│   ├── blocks_parser.py          # Block/sector metadata
│   ├── calc_basic.py             # Preclose/turnover/market-value
│   └── calc_factor.py            # HFQ factor (QUANTAXIS)
├── run_backtest.py               # Backtest CLI
├── run_dualtrend_breath_backtest.py  # DualTrend backtest CLI
├── run_pipeline.py               # Pipeline CLI
└── run_kdj_b1_analysis.py        # KDJ B1 research CLI
```

## Environment and Project Entry
- Conda env: `/home/yang/venvs/my_quant_env`
- Project root: `/home/yang/projects/my_quant_project`

```bash
eval "$(/home/yang/venvs/miniconda3/bin/conda shell.bash hook)"
conda activate /home/yang/venvs/my_quant_env
cd /home/yang/projects/my_quant_project
```

## GitHub Version Control Standard

### Start of Work
```bash
git status --short
git branch --show-current
git log --oneline -5
```
- Confirm branch, uncommitted changes, and recent checkpoints before editing.
- For risky work, create a dedicated branch such as `feature/...`, `fix/...`, or `research/...`.
- Do not start large refactors or data-pipeline edits without first understanding the current git state.

### End of Work
```bash
git diff --stat
git status
```
- Verify that only intended files changed.
- Commit validated work with a clear message and push to GitHub for a stable rollback point.
- For research or backtest milestones, record commit SHA, config path, date range, and report paths.

### Checkpoint and Rollback Discipline
- Make small checkpoint commits before and after large refactors, schema changes, and strategy rewrites.
- Prefer `git revert <sha>` or a new branch from a known good commit when backing out shared history.
- Avoid long-running experiments on top of uncommitted local changes.
- Treat the repo history as the project memory: if a change breaks behavior, recover from a known SHA and iterate again.

## Skill Sync Workflow
- Canonical source: `/home/yang/projects/my_quant_project/skills/quant-analyst-myproj/SKILL.md`
- Sync targets:
  - `/home/yang/.config/opencode/skills/quant-analyst-myproj/SKILL.md`
  - `/home/yang/.cursor/skills/quant-analyst-myproj/SKILL.md`
- After editing the canonical file, sync the platform copies and verify equality.

```bash
cmp -s /home/yang/projects/my_quant_project/skills/quant-analyst-myproj/SKILL.md /home/yang/.config/opencode/skills/quant-analyst-myproj/SKILL.md
cmp -s /home/yang/projects/my_quant_project/skills/quant-analyst-myproj/SKILL.md /home/yang/.cursor/skills/quant-analyst-myproj/SKILL.md
```

- If project-specific Codex or Claude Code copies are added later, sync them from the repo copy first.
- Keep the project skill under git so skill evolution is versioned together with the codebase.

## Database Configuration

### PostgreSQL (Docker)
- Container: `pg_quant` (postgres:16-alpine)
- DSN: `host=localhost port=5432 dbname=quant_db user=quant password=quant123`
- Schema: `tdx`
- Override via env: `QUANT_DB_DSN="host=... dbname=... user=... password=..."`

### Database Schema
| Table/View | Description | Scale |
|------------|-------------|-------|
| `tdx.securities` | Securities master (stock/index/ETF) | ~12K |
| `tdx.daily_kline` | Daily OHLCV (unified storage) | ~28M |
| `tdx.gbbq` | Corporate actions (GBBQ decrypted) | ~180K |
| `tdx.stocks_basic` | Preclose/change%/turnover/market-value | ~28M |
| `tdx.adjust_factor` | HFQ adjustment factors | ~28M |
| `tdx.blocks_info` | Block/sector master table | ~1K |
| `tdx.blocks_member` | Block constituents | ~77K |
| `tdx.holidays` | Holiday calendar | ~600 |
| `tdx.v_bfq_daily` | Unadjusted daily view | view |
| `tdx.v_qfq_daily` | Forward-adjusted (前复权) view | view |
| `tdx.v_hfq_daily` | Backward-adjusted (后复权) view | view |

### Data Update Commands
```bash
# Start the database container
docker start pg_quant

# Daily incremental update (run after TDX software downloads new data)
python scripts/update_daily.py --vipdoc /mnt/d/new_tdx/vipdoc --tdxhome /mnt/d/new_tdx

# Re-import GBBQ only
python scripts/import_tdx.py --steps gbbq --tdxhome /mnt/d/new_tdx

# Recalculate factors only
python scripts/import_tdx.py --steps basic,factor,views --tdxhome /mnt/d/new_tdx

# Full re-import from zip
python scripts/import_tdx.py --zip /mnt/d/TDX_hsjday.zip --tdxhome /mnt/d/new_tdx
```

### Why `update_daily.py` Runs Slowly (Known Bottlenecks)

The daily update typically takes **15–30 minutes**. Root causes in order of impact:

| # | Bottleneck | Details |
|---|---|---|
| 1 | **WSL2 `/mnt/d/` cross-filesystem I/O** | The `vipdoc/` directory lives on Windows NTFS, accessed from WSL2 via the 9P protocol. Each `file.read_bytes()` call crosses the WSL2<->Windows boundary, adding 5–50x overhead vs native Linux I/O. ~12,000 files x slow read = dominant cost. |
| 2 | **Single-threaded sequential file scan** | `collect_day_files` + `parse_day_file` loop serially — no parallelism. |
| 3 | **Full file re-read on incremental update** | Every `.day` file is read in full (`read_bytes()`) and all records unpacked, even when only the last 1–2 rows are new. A 30-year stock file has ~7,000 records x 32 bytes = ~224 KB parsed to get 1 new row. |
| 4 | **`or True` forces full recalculation always** | Line 235 of `update_daily.py`: `if new_rows > 0 or True:` — the `or True` is a debug artifact that was never removed. It forces GBBQ re-import, calc_basic, and calc_factor to run even when there are 0 new rows. |
| 5 | **calc_basic / calc_factor are full recalculations** | Both scripts iterate all ~12,000 symbols x full history: ~12,000 individual `SELECT ... WHERE symbol = %s ORDER BY date` round-trips to PostgreSQL each, then Python-loop processing of ~28M rows total. |
| 6 | **Python-loop data processing (no vectorization)** | Both calc scripts use pure Python `for` loops over rows, not vectorized NumPy/Pandas. |

**Mitigation options** (not yet implemented):
- Copy `vipdoc/` to WSL2 native filesystem (`~/`) before running update, then delete after.
- Parallelize `parse_day_file` with `concurrent.futures.ThreadPoolExecutor`.
- In `update_kline`, seek to the tail of each `.day` file (only read last `N x 32` bytes).
- Remove the `or True` to skip recalc when no new rows.
- Make calc_basic/calc_factor incremental: only process symbols with new dates.

### Data Loading API
```python
from quant.data.loader import load_symbol_db, list_symbols_from_db, load_symbol

# DB loader (recommended)
df = load_symbol_db('sz000001', start='2024-01-01', adjust='qfq')

# Alias: load_symbol == load_symbol_db
df = load_symbol('sz000001', start='2024-01-01')

# List symbols from DB
symbols = list_symbols_from_db(sec_type='stock', exclude_boards={'star', 'bse'})
```

## Data Layout & Pricing

### Database (single source of truth)
Adjustment factors via QUANTAXIS algorithm:
```
hfq_factor: on ex-right dates, ratio = prev_close / preclose_adjusted
qfq_factor = hfq_factor / latest_hfq_factor
adj_price = raw_price * qfq_factor  (forward adjusted)
adj_price = raw_price * hfq_factor  (backward adjusted)
```

## Config Schema (Pipeline)
```yaml
steps:
  backtest: true

data:
  symbols: []
  max_stocks: 0
  exclude_boards: [star]

backtest:
  type: kdj_forward_return
  start: 2015-01-01
  end: 2024-12-31
  kdj:
    n: 9
    k: 3
    d: 3
    j_threshold: 0
  horizons: [1, 3, 5]
  report_dir: backtest_results
```

## Operational Standard
- Always start PostgreSQL container (`docker start pg_quant`) before running backtests.
- Run `update_daily.py` after TDX software downloads latest data.
- Check git status at the start of a task and verify git state again when the task ends.
- Keep repo-backed checkpoint commits around risky refactors, schema changes, and research milestones.
- Confirm STAR board exclusion for A-share backtests.
- Enforce T+1 entry (signal day close -> next day open).
- Avoid look-ahead bias: indicators must use data up to t only.

## Research & Backtesting Standards (Professional)
### Research Workflow
- Start with a hypothesis, define signal logic and constraints.
- Use multi-horizon forward returns (1/3/5/10/20 days) and multiple regimes.
- Separate research data prep from trading rules to avoid leakage.

### Backtesting Integrity Checklist
- No look-ahead: indicators and features use data up to t; signals enter at t+1 open.
- Survivorship control: avoid filtering by future listing status; respect IPO start date.
- Corporate actions: use adjustment factors from `tdx.adjust_factor`.
- Trading constraints: include suspensions, limit-up/down, liquidity, and T+1 rules.
- Costs: apply commission, stamp tax, and slippage assumptions.

### Risk & Performance Metrics
- Win rate, average/median return, profit factor, hit ratio by regime.
- Drawdown metrics: max drawdown, average drawdown, time-to-recover.
- Risk-adjusted: Sharpe, Sortino, Calmar (annualized where appropriate).
- Tail risk: skew, kurtosis, CVaR/Expected Shortfall.

### A-share Specific Rules
- Enforce T+1 settlement for buys; no same-day sell of new buys.
- Handle limit-up/down and suspensions; skip non-tradable entries.
- Consider ST/other special treatment filters when relevant.
- Always confirm whether to exclude STAR board before each run.

## Performance & Hardware
- Host: 9900X + RTX5090. Use multithreading/multiprocessing for batch runs.
- Consider CUDA/torch for heavy factor research or DL models; keep backtests CPU-parallel.

## Engineering Standards
- Prefer vectorized Pandas/NumPy for signal generation.
- Strictly avoid look-ahead bias; use point-in-time data only.
- Always include transaction costs and slippage in strategy backtests.
- Keep modules small, composable, and CLI-friendly.
- Treat repo-tracked skills and configs as versioned project assets, not disposable notes.

## Interfaces Summary
- `quant.data.loader.load_symbol_db(symbol, start, end, adjust)`
- `quant.data.loader.load_symbol(symbol, start, end, adjust)` — alias for load_symbol_db
- `quant.data.loader.list_symbols_from_db(sec_type, exclude_boards)`
- `quant.backtest.engine.run_kdj_forward_return_backtest(symbols, start, end, ...)`
- `quant.backtest.engine.run_dualtrend_breath_backtest(symbols, start, end, ...)`
- `quant.db.connection.get_connection(dsn)`
- `quant.db.schema.init_schema(conn)` / `create_views(conn)`
- `quant.pipeline.run_pipeline(config_path)`

## How to Extend
- Add indicators to `quant/indicators/`
- Add new strategies to `quant/backtest/strategies.py`
- Add new pipeline steps in `quant/pipeline.py`
- Add new DB tables in `quant/db/schema.py`
- Update `configs/*.yaml` for new workflows
- Update the repo skill first, then sync local platform copies when project conventions change
