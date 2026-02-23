---
name: quant-analyst-myproj
description: Quant analyst skill tailored to the my_quant_project backtesting platform with Backtrader workflows, data pipeline, and reporting.
---

# Quant Analyst (My Quant Project)

## Purpose
Expert in quantitative finance, algorithmic trading strategies, and financial data analysis, specialized for the `my_quant_project` codebase. Provides rigorous backtesting, risk-aware analytics, and clean engineering practices using the Python scientific stack and Backtrader.

## When to Use
- Build or extend A-share backtests in `my_quant_project`
- Add indicators, signals, or strategy logic
- Run or automate data download, quality checks, and reporting
- Refactor the pipeline or config-driven workflows
- Design research metrics or validation protocols

## Quick Start (Project Commands)
```bash
# Activate environment and enter project
source /home/yang/venvs/my_quant_env/bin/activate
cd /home/yang/projects/my_quant_project

# Token from /home/yang/tk.csv (column token) or env

# Data download (raw_price + adj_factor)
python data_downloader.py --stocklist stocklist.csv --start 20040101 --end today --workers 5 --exclude-boards star --missing-only

# Data quality batch check + adj_price cache
python data_quality.py --data-dir data --output-dir data_clean --exclude-boards star

# KDJ J<0 forward-return backtest (uses adj_price)
python run_backtest.py --data-dir data_clean --start 2015-01-01 --end 2024-12-31

# Config-driven pipeline (prepare -> backtest)
python run_pipeline.py --config configs/pipeline_prepare.yaml
python run_pipeline.py --config configs/pipeline_kdj_j0.yaml
```

## Repository Context (Key Modules)
```
my_quant_project/
├── configs/                     # Pipeline configs
├── data/                        # raw_price + adj_factor
├── data_clean/                  # raw_price + adj_factor + adj_price
├── backtest_results/            # Backtest reports
├── quant/
│   ├── backtest/engine.py        # Backtrader entrypoints
│   ├── backtest/strategies.py    # KDJ forward-return strategy
│   ├── data/downloader.py        # Tushare downloader
│   ├── data/loader.py            # CSV loader + symbol resolution
│   ├── data/quality.py           # Data quality checks
│   ├── indicators/kdj.py         # KDJ indicator
│   ├── reporting/report.py       # CSV/MD report generation
│   └── pipeline.py               # Config-driven pipeline
├── run_backtest.py               # Backtest CLI
├── run_pipeline.py               # Pipeline CLI
├── data_downloader.py            # Downloader wrapper
├── data_quality.py               # Quality wrapper
└── configs/pipeline_kdj_j0.yaml   # Example pipeline config
```

## Environment and Project Entry
- Virtualenv: `/home/yang/venvs/my_quant_env`
- Project root: `/home/yang/projects/my_quant_project`

```bash
source /home/yang/venvs/my_quant_env/bin/activate
cd /home/yang/projects/my_quant_project
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
  download:
    start: 20040101
    end: today
    workers: 5
    exclude_boards: []
    overwrite: false
    limit: 0

quality:
  output_dir: data_clean
  remove_suspension: true
  mark_limit_price: true
  handle_outliers: true
  generate_adj_price: true

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

## Data Layout & Pricing
```
data/
├── raw_price/    # OHLCV
└── adj_factor/   # adj factor

data_clean/
├── raw_price/    # cleaned raw + limit/suspension flags
├── adj_factor/   # cleaned adj factors
└── adj_price/    # cached adjusted prices
```

Pricing rule (point-in-time safe):
```
adj_price = raw_price * factor.iloc[-1] / factor
```

## Operational Standard
- Always run update + clean before backtest (use `pipeline_prepare.yaml`).
- Confirm STAR board exclusion for A-share backtests (add `exclude_boards: [star]`).
- Enforce T+1 entry (signal day close -> next day open).
- Avoid look-ahead bias: indicators must use data up to t only; shift signals when needed.

## Performance & Hardware
- Host: 9900X + RTX5090. Use multithreading/multiprocessing for batch runs.
- Consider CUDA/torch for heavy factor research or DL models; keep backtests CPU-parallel.

## Engineering Standards (Project Expectations)
- Prefer vectorized Pandas/NumPy for signal generation.
- Strictly avoid look-ahead bias; use point-in-time data only.
- Always include transaction costs and slippage in strategy backtests.
- Use log returns for statistical modeling, simple returns for reporting.
- Validate models with walk-forward or out-of-sample testing.
- Keep modules small, composable, and CLI-friendly.

## Research Best Practices (From quant-analyst Skill)
- Include realistic trading constraints: limit moves, suspensions, liquidity.
- Use robust statistics and avoid normality assumptions for tail risk.
- Prefer multi-horizon evaluation (1/3/5/10/20 days).
- Parameterize assumptions; avoid hardcoding market rules.

## Anti-Patterns
- Overfitting to historical data
- Ignoring transaction costs or execution constraints
- Using future data in signal generation
- Hardcoding market assumptions without stress testing

## Interfaces Summary
- `quant.data.downloader.download_kline(...)`
- `quant.data.quality.DataQualityChecker` + `batch_process_stocks(...)`
- `quant.backtest.engine.run_kdj_forward_return_backtest(...)`
- `quant.reporting.report.write_report(...)`
- `quant.pipeline.run_pipeline(config_path)`

## How to Extend
- Add indicators to `quant/indicators/`
- Add new strategies to `quant/backtest/strategies.py`
- Add new pipeline steps in `quant/pipeline.py`
- Update `configs/*.yaml` for new workflows
