"""CLI wrapper for quant.data.quality."""

from __future__ import annotations

import argparse
import logging

from quant.data.loader import (
    list_symbols_from_data_dir,
    load_symbols_from_stocklist,
    normalize_symbols,
    filter_symbols_by_boards,
)
from quant.data.quality import DataQualityChecker, batch_process_stocks

__all__ = ["DataQualityChecker", "batch_process_stocks"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run data quality checks and cleaning")
    parser.add_argument("--data-dir", default="data", help="Base data directory")
    parser.add_argument("--output-dir", default="data_clean", help="Output clean data directory")
    parser.add_argument("--stocklist", default="stocklist.csv", help="CSV with symbol/ts_code")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols")
    parser.add_argument("--max-stocks", type=int, default=0)
    parser.add_argument(
        "--exclude-boards",
        nargs="*",
        default=[],
        choices=["gem", "star", "bj"],
    )
    parser.add_argument("--keep-suspension", action="store_true", default=False)
    parser.add_argument("--no-mark-limit-price", action="store_true", default=False)
    parser.add_argument("--no-handle-outliers", action="store_true", default=False)
    parser.add_argument("--no-adj-price", action="store_true", default=False)
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    args = parse_args()

    if args.symbols:
        symbols = normalize_symbols(args.symbols.split(","))
    elif args.stocklist:
        symbols = load_symbols_from_stocklist(args.stocklist, limit=args.max_stocks)
    else:
        symbols = list_symbols_from_data_dir(args.data_dir)
        if args.max_stocks > 0:
            symbols = symbols[: args.max_stocks]

    symbols = filter_symbols_by_boards(symbols, set(args.exclude_boards or []))

    if not symbols:
        raise SystemExit("No symbols found for quality check")

    remove_suspension = not args.keep_suspension
    mark_limit_price = not args.no_mark_limit_price
    handle_outliers = not args.no_handle_outliers
    generate_adj_price = not args.no_adj_price

    batch_process_stocks(
        symbols=symbols,
        data_dir=args.data_dir,
        output_dir=args.output_dir,
        remove_suspension=remove_suspension,
        mark_limit_price=mark_limit_price,
        handle_outliers=handle_outliers,
        generate_adj_price=generate_adj_price,
    )

    logging.info("Quality processing complete. Output: %s", args.output_dir)


if __name__ == "__main__":
    main()
