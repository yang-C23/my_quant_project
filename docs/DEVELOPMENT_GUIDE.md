# Development Guide

This document provides a quick-start reference for contributors (human or AI) so the project structure, workflows, and expectations are immediately clear.

## 1. Project Layout

| Path | Purpose | Notes / Usage |
|------|---------|---------------|
| `data/` | Tushare CSV cache per `ts_code`. | Created by `data_downloader.py`. |
| `models/` | Persisted ML artefacts (`joblib`, etc.). | Populated by `ml_trainer.py`. |
| `backtest_results/` | Metrics JSON and plots from backtests. | File names depend on the runner script. |
| `custom_indicators/` | Drop-in Backtrader indicator implementations. | Add new modules with docstrings + usage snippets. |
| `custom_strategies/` | Strategy classes consumed by the backtest engine. | Includes `moving_average` (baseline) and `dual_line_breath` skeleton. |
| `factor_lib/` | Factor computation utilities (custom + Alpha101). | Importable by both research notebooks and strategies. |
| `docs/` | Project documentation (`DEVELOPMENT_GUIDE.md`, etc.). | Extend with additional design notes as needed. |
| `backtest_engine.py` | Shared Backtrader orchestration (data feed + analytics + plotting). | Invoke via CLI or call `run_backtest` from Python. |
| `baseline_backtest.py` | Wrapper for the MA crossover strategy. | Delegates to `backtest_engine`. |
| `rule_strategy_backtest.py` | Wrapper for the future dual-line breath strategy. | Replace placeholder logic in `custom_strategies/dual_line_breath.py`. |
| `ml_strategy_backtest.py` | Wrapper for ML-driven strategies. | Expects a saved model and custom inference logic. |
| `data_downloader.py` | Batch downloads via Tushare Pro (`pro.stock_basic`, `pro_bar`, `index_daily`). | Supports stock lists, manual symbols, and index downloads. |
| `ml_trainer.py` | Example RandomForest training pipeline. | Update once real features/labels are defined. |
| `factor_analysis.py` | IC/ICIR helper functions. | Extend with aggregation utilities as factors mature. |

## 2. Environment Workflow

1. **Create & Activate Conda env**
   ```bash
   conda create -y -p /home/yang/venvs/my_quant_env python=3.10
   conda activate /home/yang/venvs/my_quant_env
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```
2. **Optional** — set Matplotlib cache to a writable directory to avoid permission warnings:
   ```bash
   export MPLCONFIGDIR="$PWD/.matplotlib"
   ```
3. **Credentials** — export the Tushare Pro token (never hardcode it):
   ```bash
   export TUSHARE_TOKEN="26...b4"  # replace with the actual token
   ```

## 3. Data Acquisition

Tushare Pro endpoints are used exclusively. The CLI mirrors the resilient workflow from `StockTradebyZ/fetch_kline.py`.

```bash
# Download the curated universe from a stock list
python data_downloader.py \
  --stocklist /home/yang/projects/StockTradebyZ/stocklist.csv \
  --max-workers 6 \
  --start-date 20050101 --adjust qfq

# Target specific equities + indices (re-run with --overwrite for refresh)
python data_downloader.py \
  --symbols 000001.SZ 000002.SZ \
  --index-symbols 000852.SH 000300.SH \
  --start-date 20200101 --adjust qfq --overwrite
```

- Use `--limit` for a quick sanity check (e.g. `--limit 20`).
- Raw CSVs land in `data/<ts_code>.csv` with columns `[trade_date, open, high, low, close, volume]`.

## 4. Backtesting Framework

### Shared Engine (`backtest_engine.py`)

```bash
python backtest_engine.py \
  --symbol 000001.SZ \
  --strategy custom_strategies.moving_average:MovingAverageCrossStrategy \
  --strategy-params short_window=5 long_window=20 \
  --benchmark-symbols 000852.SH 000300.SH
```

- Outputs metrics JSON (Sharpe, max drawdown, win rate, profit factor) and a cumulative growth plot (strategy vs. benchmarks) under `backtest_results/`.
- Accepts any Backtrader strategy class reachable by dotted path.
- Strategy parameters (`--strategy-params`) accept `key=value` pairs and auto-cast to `int`, `float`, `bool`, or `str`.

### Convenience Wrappers

| Script | Purpose | How to Use |
|--------|---------|------------|
| `baseline_backtest.py` | 5/20 MA crossover sanity-check. | `python baseline_backtest.py --symbol 000001.SZ` |
| `rule_strategy_backtest.py` | Dual-line breath strategy runner (placeholder). | `python rule_strategy_backtest.py --symbol 000001.SZ` |
| `ml_strategy_backtest.py` | ML signal runner (loads model, placeholder logic). | `python ml_strategy_backtest.py --symbol 000001.SZ --model-path models/random_forest.pkl` |

All wrappers ultimately call `run_backtest` and generate the same artefacts as the generic engine.

## 5. Strategy & Indicator Development

- Custom strategies live in `custom_strategies/`. Each module should expose a public class and document usage (see `moving_average.py`).
- Indicators belong in `custom_indicators/`. Keep the APIs lightweight and documented.
- To register a new strategy with the CLI, either:
  1. Add it to `custom_strategies/__init__.py` and reference via dotted path, or
  2. Pass the fully qualified module path to `backtest_engine.py`.

## 6. Machine Learning Pipeline

- `ml_trainer.py` demonstrates a minimal RandomForest workflow. Replace the dataset (`data/training_sample.csv`) and model architecture as research evolves.
- `ml_strategy_backtest.py` expects the trained model to expose a `predict` method. Add feature engineering inside `MLSignalStrategy.next()`.

## 7. Miscellaneous Notes

- Matplotlib plots are saved automatically; set `MPLCONFIGDIR` if you need GUI rendering.
- All scripts are designed to be token-agnostic. Never commit credentials—rely on environment variables.
- The repository intentionally avoids executing long-running jobs by default. After permission upgrades (e.g. Tushare Pro access), re-run the relevant commands manually.

Happy hacking!
