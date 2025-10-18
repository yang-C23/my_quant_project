# My Quant Project

Quantitative research and trading framework scaffold covering data ingestion, factor research, machine learning, and backtesting. The project is organised so that new strategies (rule-based or ML-driven) can be evaluated on a single, shared Backtrader engine.

## Environment Setup
- Create the Conda environment (Python 3.10) inside `/home/yang/venvs`:
  ```bash
  conda create -y -p /home/yang/venvs/my_quant_env python=3.10
  conda activate /home/yang/venvs/my_quant_env
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
  ```
- (Optional) Point Matplotlib to a writable cache to silence warnings:
  ```bash
  export MPLCONFIGDIR="$PWD/.matplotlib"
  ```
- Backtrader is available both via PyPI (installed by `requirements.txt`) and the local clone at `/home/yang/projects/backtrader`. If you prefer the local checkout, add it to `PYTHONPATH`.

## Configuration
- Never hardcode credentials. Export the Tushare token before running scripts:
  ```bash
  export TUSHARE_TOKEN="your_token_here"
  ```
- Data directory: `data/`
- Models directory: `models/`

## Workflow
- **Step 0** — `data_downloader.py`: fetch A-share daily data through Tushare Pro.
- **Step 1** — `backtest_engine.py`: reusable Backtrader runner for any strategy class.
- **Step 2** — `baseline_backtest.py`: thin wrapper over the engine using the MA strategy.
- **Step 3** — `rule_strategy_backtest.py`: wrapper for the dual-line breath strategy.
- **Step 4** — `factor_analysis.py`: factor IC/ICIR studies.
- **Step 5** — `ml_trainer.py`: feature engineering and ML model training.
- **Step 6** — `ml_strategy_backtest.py`: ML strategy runner (extends the shared engine).
- **Step 7** — `regime_detector.py`: market state classification utilities.

## Data Download
- The downloader now targets **Tushare Pro** endpoints exclusively. Reference token permissions (e.g. rate limits) before launching a full run.
- Download the entire stock universe based on an external stock list:
  ```bash
  python data_downloader.py \
    --stocklist /home/yang/projects/StockTradebyZ/stocklist.csv \
    --max-workers 6 \
    --start-date 20050101 --adjust qfq
  ```
- Fetch specific equities or indices:
  ```bash
  python data_downloader.py \
    --symbols 000001.SZ 000002.SZ \
    --index-symbols 000300.SH 000852.SH \
    --start-date 20200101 --adjust qfq --overwrite
  ```
- Use `--limit` to dry-run with a subset before downloading the full universe. CSV files are saved under `data/<ts_code>.csv`.

## Backtesting
- The shared engine supports any dotted strategy path:
  ```bash
  python backtest_engine.py \
    --symbol 000001.SZ \
    --strategy custom_strategies.moving_average:MovingAverageCrossStrategy \
    --strategy-params short_window=5 long_window=20 \
    --benchmark-symbols 000852.SH 000300.SH
  ```
- Wrapper scripts provide pre-configured defaults:
  ```bash
  python baseline_backtest.py --symbol 000001.SZ \
    --benchmark-symbols 000852.SH 000300.SH
  ```
- Metrics (Sharpe, max drawdown, win rate, profit factor) are written to `backtest_results/*.json`.
- The cumulative return comparison chart (strategy vs. benchmarks) is saved as a growth percentage plot under `backtest_results/*.png`. Use `--plot` with the generic engine to display Backtrader’s built-in chart.

## Further Reading
- `docs/DEVELOPMENT_GUIDE.md` describes the project structure, environment workflow, and usage examples for newly added modules.
