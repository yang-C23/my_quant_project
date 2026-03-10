---
name: quant-analyst-myproj
description: Quant analyst skill tailored to the my_quant_project backtesting platform with Backtrader workflows, PostgreSQL data pipeline, TDX import, and reporting.
---

# Quant Analyst (My Quant Project)

## Purpose
Expert in quantitative finance, algorithmic trading strategies, and financial data analysis, specialized for the `my_quant_project` codebase. Provides rigorous backtesting, risk-aware analytics, and clean engineering practices using the Python scientific stack, Backtrader, and PostgreSQL.

## When to Use
- Build or extend A-share backtests in `my_quant_project`
- Add indicators, signals, or strategy logic
- Import, update, or query TDX market data in PostgreSQL
- Run or automate data download, quality checks, and reporting
- Refactor the pipeline or config-driven workflows
- Design research metrics or validation protocols

## Quick Start (Project Commands)
```bash
# Activate environment and enter project
eval "$(/home/yang/venvs/miniconda3/bin/conda shell.bash hook)"
conda activate /home/yang/venvs/my_quant_env
cd /home/yang/projects/my_quant_project

# ── Database operations ──

# Start PostgreSQL (Docker)
docker start pg_quant

# Full import from TDX (first time only)
python scripts/import_tdx.py --zip /mnt/d/TDX_hsjday.zip --tdxhome /mnt/d/new_tdx

# Daily incremental update (after TDX downloads latest data)
python scripts/update_daily.py --vipdoc /mnt/d/new_tdx/vipdoc --tdxhome /mnt/d/new_tdx

# ── Legacy CSV operations (optional) ──

# Data download via Tushare (raw_price + adj_factor)
python data_downloader.py --stocklist stocklist.csv --start 20040101 --end today --workers 5 --exclude-boards star --missing-only

# Data quality batch check + adj_price cache
python data_quality.py --data-dir data --output-dir data_clean --exclude-boards star

# ── Backtesting ──

# KDJ J<0 forward-return backtest (default: uses DB)
python run_backtest.py --data-dir data_clean --start 2015-01-01 --end 2024-12-31

# Config-driven pipeline
python run_pipeline.py --config configs/pipeline_prepare.yaml
python run_pipeline.py --config configs/pipeline_kdj_j0.yaml
```

## Repository Context (Key Modules)
```
my_quant_project/
├── configs/                     # Pipeline configs
├── backtest_results/            # Backtest reports
├── quant/
│   ├── backtest/engine.py        # Backtrader entrypoints (DB/CSV)
│   ├── backtest/strategies.py    # KDJ, DualTrend strategies
│   ├── data/downloader.py        # Tushare downloader (CSV)
│   ├── data/loader.py            # DB + CSV loader + symbol resolution
│   ├── data/quality.py           # Data quality checks
│   ├── db/connection.py          # PostgreSQL connection manager
│   ├── db/schema.py              # DDL: tables, indexes, views
│   ├── indicators/               # KDJ, DualTrend, VolBreath, Brick
│   ├── reporting/report.py       # CSV/MD report generation
│   └── pipeline.py               # Config-driven pipeline
├── scripts/
│   ├── import_tdx.py             # Full TDX → PostgreSQL import
│   ├── update_daily.py           # Incremental daily update
│   ├── tdx_parser.py             # TDX binary .day parser
│   ├── gbbq_decoder.py           # GBBQ decryption
│   ├── blocks_parser.py          # Block/sector metadata
│   ├── calc_basic.py             # Preclose/turnover/market-value
│   └── calc_factor.py            # HFQ factor (QUANTAXIS)
├── run_backtest.py               # Backtest CLI
├── run_pipeline.py               # Pipeline CLI
└── stocklist.csv
```

## Environment and Project Entry
- Conda env: `/home/yang/venvs/my_quant_env`
- Project root: `/home/yang/projects/my_quant_project`

```bash
eval "$(/home/yang/venvs/miniconda3/bin/conda shell.bash hook)"
conda activate /home/yang/venvs/my_quant_env
cd /home/yang/projects/my_quant_project
```

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

# Daily incremental update (run after TDX downloads new data)
python scripts/update_daily.py --vipdoc /mnt/d/new_tdx/vipdoc --tdxhome /mnt/d/new_tdx

# Re-import GBBQ only
python scripts/import_tdx.py --steps gbbq --tdxhome /mnt/d/new_tdx

# Recalculate factors only
python scripts/import_tdx.py --steps basic,factor,views --tdxhome /mnt/d/new_tdx

# Full re-import from zip
python scripts/import_tdx.py --zip /mnt/d/TDX_hsjday.zip --tdxhome /mnt/d/new_tdx
```

### Data Loading API
```python
from quant.data.loader import load_symbol_db, list_symbols_from_db, load_symbol

# DB loader (default, recommended)
df = load_symbol_db('sz000001', start='2024-01-01', adjust='qfq')

# Unified loader (DB by default, CSV fallback)
df = load_symbol('sz000001', start='2024-01-01', source='db')
df = load_symbol('000001', start='2024-01-01', source='csv', data_dir='data_clean')

# List symbols from DB
symbols = list_symbols_from_db(sec_type='stock', exclude_boards={'star', 'bse'})
```

## Data Layout & Pricing

### Database (primary)
Adjustment factors via QUANTAXIS algorithm:
```
hfq_factor: on ex-right dates, ratio = prev_close / preclose_adjusted
qfq_factor = hfq_factor / latest_hfq_factor
adj_price = raw_price * qfq_factor  (forward adjusted)
adj_price = raw_price * hfq_factor  (backward adjusted)
```

### CSV (legacy, optional)
```
data/
├── raw_price/    # OHLCV
└── adj_factor/   # adj factor

data_clean/
├── raw_price/    # cleaned raw + limit/suspension flags
├── adj_factor/   # cleaned adj factors
└── adj_price/    # cached adjusted prices
```

## Config Schema (Pipeline)
```yaml
steps:
  download: false
  quality: true
  backtest: true

data:
  data_dir: data
  stocklist: stocklist.csv
  symbols: []
  max_stocks: 0
  exclude_boards: [star]

backtest:
  type: kdj_forward_return
  start: 2015-01-01
  end: 2024-12-31
  data_dir: data_clean
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

## Interfaces Summary
- `quant.data.loader.load_symbol_db(symbol, start, end, adjust)`
- `quant.data.loader.list_symbols_from_db(sec_type, exclude_boards)`
- `quant.data.loader.load_symbol(symbol, start, end, source, data_dir)`
- `quant.backtest.engine.run_kdj_forward_return_backtest(symbols, ..., source='db')`
- `quant.backtest.engine.run_dualtrend_breath_backtest(symbols, ..., source='db')`
- `quant.db.connection.get_connection(dsn)`
- `quant.db.schema.init_schema(conn)` / `create_views(conn)`
- `quant.pipeline.run_pipeline(config_path)`

## How to Extend
- Add indicators to `quant/indicators/`
- Add new strategies to `quant/backtest/strategies.py`
- Add new pipeline steps in `quant/pipeline.py`
- Add new DB tables in `quant/db/schema.py`
- Update `configs/*.yaml` for new workflows
