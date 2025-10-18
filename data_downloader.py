"""
Batch downloader for Tushare Pro daily bars.

This script mirrors the workflow used in ``StockTradebyZ/fetch_kline.py`` but is
tailored for the current project layout. It supports three common sourcing
patterns:

1. Purely automated — query the full A-share universe via ``stock_basic``.
2. Semi-automated — pass a curated stock list (CSV with ``ts_code``/``symbol``).
3. Manual — provide a text file or CLI list of specific tickers and indices.

The script only uses the Pro endpoints (`pro.stock_basic`, `ts.pro_bar`,
`pro.daily`, `pro.index_daily`) and applies back-off / retry logic to handle
transient rate limits. All credentials must be supplied through the
environment (``TUSHARE_TOKEN``) or the ``--token`` CLI flag.

Example
-------
Download the first 100 symbols from the stock universe plus CSI 300 / CSI 1000:

.. code-block:: bash

    python data_downloader.py \\
        --start-date 20100101 --adjust qfq --limit 100 \\
        --index-symbols 000300.SH 000852.SH

"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable, List, Sequence

import pandas as pd

try:
    import tushare as ts
except ImportError as exc:  # pragma: no cover - handles missing dependency at runtime
    raise SystemExit(
        "tushare package is required. Install it inside your project environment:\n"
        "  pip install tushare"
    ) from exc

PROJECT_ROOT = Path(__file__).resolve().parent
LOGGER = logging.getLogger("data_downloader")
DEFAULT_FIELDS = ["trade_date", "open", "high", "low", "close", "vol"]

RETRY_ATTEMPTS = 4
RETRY_BACKOFF = 8  # seconds


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download A-share daily data via Tushare Pro.")
    parser.add_argument("--token", help="Tushare API token (else read from TUSHARE_TOKEN env).")
    parser.add_argument("--start-date", default="20050101", help="YYYYMMDD inclusive start date.")
    parser.add_argument("--end-date", default="", help="YYYYMMDD inclusive end date (blank = latest).")
    parser.add_argument(
        "--adjust",
        default="qfq",
        choices=("qfq", "hfq", "none"),
        help="Price adjustment (qfq=前复权, hfq=后复权, none=raw prices).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "data",
        help="Directory for the generated CSV files (default: project data dir).",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing CSV files.")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of equity symbols to download (0 = all).",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        help="Manual list of ts_codes to download (e.g. 000001.SZ 600000.SH).",
    )
    parser.add_argument(
        "--symbols-file",
        type=Path,
        help="Text file with one code per line (ts_code or raw 6-digit symbol).",
    )
    parser.add_argument(
        "--stocklist",
        type=Path,
        help="CSV file containing `ts_code` or `symbol` columns (e.g. StockTradebyZ/stocklist.csv).",
    )
    parser.add_argument(
        "--index-symbols",
        nargs="*",
        help="List of index ts_codes (e.g. 000300.SH) fetched via `pro.index_daily`.",
    )
    parser.add_argument(
        "--index-symbols-file",
        type=Path,
        help="Text file with index ts_codes (one per line).",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Number of parallel download workers (default: 4).",
    )
    parser.add_argument(
        "--cooldown",
        type=float,
        default=0.8,
        help="Sleep seconds between sequential API calls (used when max_workers=1).",
    )
    return parser.parse_args(argv)


def resolve_token(cli_token: str | None) -> str:
    token = cli_token or os.getenv("TUSHARE_TOKEN")
    if not token:
        raise SystemExit("Missing Tushare token. Provide `--token` or set TUSHARE_TOKEN.")
    return token


def symbol_to_ts_code(symbol: str) -> str:
    bare = symbol.strip().upper()
    if bare.endswith((".SH", ".SZ", ".BJ")):
        return bare
    code = bare.zfill(6)
    if code.startswith(("60", "68", "9")):
        return f"{code}.SH"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def read_symbol_file(path: Path) -> List[str]:
    return [
        symbol_to_ts_code(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def load_symbols_from_stocklist(stocklist: Path) -> List[str]:
    df = pd.read_csv(stocklist)
    if "ts_code" in df.columns:
        series = df["ts_code"].dropna().astype(str)
    elif "symbol" in df.columns:
        series = df["symbol"].dropna().astype(str)
    else:
        raise SystemExit(f"`{stocklist}` must include a `ts_code` or `symbol` column.")
    return list(dict.fromkeys(series.map(symbol_to_ts_code)))


def gather_symbols(pro: "ts.pro_api", args: argparse.Namespace) -> tuple[list[str], set[str]]:
    manual: list[str] = []
    if args.symbols_file:
        if not args.symbols_file.exists():
            raise SystemExit(f"Symbols file not found: {args.symbols_file}")
        manual.extend(read_symbol_file(args.symbols_file))
    if args.symbols:
        manual.extend(symbol_to_ts_code(code) for code in args.symbols)
    if args.stocklist:
        if not args.stocklist.exists():
            raise SystemExit(f"Stock list not found: {args.stocklist}")
        manual.extend(load_symbols_from_stocklist(args.stocklist))

    index_codes: list[str] = []
    if args.index_symbols_file:
        if not args.index_symbols_file.exists():
            raise SystemExit(f"Index symbols file not found: {args.index_symbols_file}")
        index_codes.extend(read_symbol_file(args.index_symbols_file))
    if args.index_symbols:
        index_codes.extend(symbol_to_ts_code(code) for code in args.index_symbols)

    index_set = set(index_codes)
    manual.extend(index_codes)

    if manual:
        ordered = list(dict.fromkeys(manual))
        if args.limit:
            ordered = ordered[: args.limit]
        return ordered, index_set

    LOGGER.info("Querying active stock universe via pro.stock_basic() ...")
    stocks = pro.stock_basic(exchange="", list_status="L", fields="ts_code")
    if stocks.empty:
        raise SystemExit("No instruments returned from stock_basic; check account permissions.")
    symbols = stocks["ts_code"].tolist()
    if args.limit:
        symbols = symbols[: args.limit]
    return symbols, index_set


def normalize_frame(df: pd.DataFrame, rename: dict[str, str]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    frame = df.rename(columns=rename).copy()
    required = ["trade_date", "open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in frame.columns]
    if missing:
        raise ValueError(f"Missing columns {missing} in returned dataframe")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame.dropna(subset=["trade_date"], inplace=True)
    return frame.sort_values("trade_date").reset_index(drop=True)


def fetch_equity_bars(
    pro: "ts.pro_api",
    ts_code: str,
    start_date: str,
    end_date: str,
    adjust: str,
) -> pd.DataFrame:
    rename_map = {"vol": "volume"}
    last_error: Exception | None = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            if adjust == "none":
                df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date, fields=",".join(DEFAULT_FIELDS))
            else:
                df = ts.pro_bar(
                    ts_code=ts_code,
                    adj=adjust,
                    start_date=start_date,
                    end_date=end_date,
                    freq="D",
                    factors=False,
                    api=pro,
                )
            return normalize_frame(df, rename_map)
        except Exception as exc:  # pragma: no cover - depends on remote API state
            last_error = exc
            sleep_for = RETRY_BACKOFF * attempt
            LOGGER.warning("Retrying %s (attempt %d/%d) after error: %s", ts_code, attempt, RETRY_ATTEMPTS, exc)
            time.sleep(sleep_for)
    raise RuntimeError(f"Failed to fetch {ts_code} after {RETRY_ATTEMPTS} attempts") from last_error


def fetch_index_bars(
    pro: "ts.pro_api",
    ts_code: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    rename_map = {"vol": "volume"}
    last_error: Exception | None = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            df = pro.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            return normalize_frame(df, rename_map)
        except Exception as exc:  # pragma: no cover
            last_error = exc
            sleep_for = RETRY_BACKOFF * attempt
            LOGGER.warning("Retrying index %s (attempt %d/%d) after error: %s", ts_code, attempt, RETRY_ATTEMPTS, exc)
            time.sleep(sleep_for)
    raise RuntimeError(f"Failed to fetch index {ts_code} after {RETRY_ATTEMPTS} attempts") from last_error


def download_symbol(
    pro: "ts.pro_api",
    ts_code: str,
    output_dir: Path,
    start_date: str,
    end_date: str,
    adjust: str,
    is_index: bool,
    overwrite: bool,
) -> tuple[str, bool, str | None]:
    target_file = output_dir / f"{ts_code}.csv"
    if target_file.exists() and not overwrite:
        return ts_code, True, None

    if is_index:
        df = fetch_index_bars(pro, ts_code, start_date, end_date)
    else:
        df = fetch_equity_bars(pro, ts_code, start_date, end_date, adjust)

    if df.empty:
        message = "no data returned"
        LOGGER.info("Skipping %s (%s).", ts_code, message)
        return ts_code, False, message

    df["trade_date"] = df["trade_date"].dt.strftime("%Y%m%d")
    df.to_csv(target_file, index=False)
    LOGGER.info("Saved %s rows for %s -> %s", len(df), ts_code, target_file.name)
    return ts_code, False, None


def run_batch_download(
    pro: "ts.pro_api",
    symbols: Sequence[str],
    index_set: set[str],
    output_dir: Path,
    start_date: str,
    end_date: str,
    adjust: str,
    overwrite: bool,
    max_workers: int,
    cooldown: float,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(symbols)
    LOGGER.info("Starting download for %d symbols (adjust=%s).", total, adjust)

    if max_workers <= 1:
        for idx, ts_code in enumerate(symbols, start=1):
            LOGGER.info("[%d/%d] Fetching %s", idx, total, ts_code)
            download_symbol(
                pro=pro,
                ts_code=ts_code,
                output_dir=output_dir,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
                is_index=ts_code in index_set,
                overwrite=overwrite,
            )
            time.sleep(cooldown)
        return

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                download_symbol,
                pro,
                ts_code,
                output_dir,
                start_date,
                end_date,
                adjust,
                ts_code in index_set,
                overwrite,
            ): ts_code
            for ts_code in symbols
        }

        for idx, future in enumerate(as_completed(future_map), start=1):
            ts_code = future_map[future]
            try:
                code, skipped, message = future.result()
                status = "skipped" if skipped else "done"
                extra = f" ({message})" if message else ""
                LOGGER.info("[%d/%d] %s %s%s", idx, total, code, status, extra)
            except Exception as exc:  # pragma: no cover - depends on network conditions
                LOGGER.error("[%d/%d] %s failed: %s", idx, total, ts_code, exc)


def main(argv: Iterable[str] | None = None) -> None:
    configure_logging()
    args = parse_args(argv)
    token = resolve_token(args.token)

    os.environ.setdefault("NO_PROXY", "api.waditu.com,.waditu.com,waditu.com")
    os.environ.setdefault("no_proxy", os.environ["NO_PROXY"])
    ts.set_token(token)

    pro = ts.pro_api()
    symbols, index_set = gather_symbols(pro, args)

    run_batch_download(
        pro=pro,
        symbols=symbols,
        index_set=index_set,
        output_dir=args.output_dir,
        start_date=args.start_date,
        end_date=args.end_date,
        adjust=args.adjust,
        overwrite=args.overwrite,
        max_workers=args.max_workers,
        cooldown=args.cooldown,
    )


if __name__ == "__main__":
    main()
