from __future__ import annotations

import argparse
import datetime as dt
import logging

from quant.backtest.engine import run_kdj_forward_return_backtest
from quant.data.loader import list_symbols_from_db, normalize_symbols
from quant.reporting.report import summarize_overall, summarize_results, write_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest KDJ J<0 forward returns")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols (e.g. sz000001,sz000002)")
    parser.add_argument("--max-stocks", type=int, default=0, help="Limit number of symbols from DB")
    parser.add_argument("--exclude-boards", default="star", help="Comma-separated boards to exclude")
    parser.add_argument("--start", default="", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default="", help="End date YYYY-MM-DD")

    parser.add_argument("--kdj-n", type=int, default=9)
    parser.add_argument("--kdj-k", type=int, default=3)
    parser.add_argument("--kdj-d", type=int, default=3)
    parser.add_argument("--j-threshold", type=float, default=0.0)
    parser.add_argument("--horizons", default="1,3,5", help="Forward days, comma-separated")
    parser.add_argument("--output-dir", default="backtest_results")

    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    args = parse_args()

    horizons = tuple(int(h) for h in args.horizons.split(",") if h.strip())
    start = args.start or None
    end = args.end or None

    if args.symbols:
        symbols = normalize_symbols(args.symbols.split(","))
    else:
        exclude_boards = set(b.strip() for b in args.exclude_boards.split(",") if b.strip())
        symbols = list_symbols_from_db(sec_type="stock", exclude_boards=exclude_boards)
        if args.max_stocks > 0:
            symbols = symbols[: args.max_stocks]

    if not symbols:
        raise SystemExit("No symbols found. Check --symbols or DB connection")

    results = run_kdj_forward_return_backtest(
        symbols=symbols,
        start=start,
        end=end,
        kdj_n=args.kdj_n,
        kdj_k=args.kdj_k,
        kdj_d=args.kdj_d,
        j_threshold=args.j_threshold,
        horizons=horizons,
    )

    per_symbol = summarize_results(results, horizons)
    overall = summarize_overall(results, horizons)

    summary = per_symbol
    if not overall.empty:
        summary = overall._append(per_symbol, ignore_index=True)

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"kdj_j{args.j_threshold:g}_{timestamp}"
    outputs = write_report(summary, output_dir=args.output_dir, prefix=prefix)

    print("Report saved:")
    print(f"- {outputs['csv']}")
    print(f"- {outputs['md']}")


if __name__ == "__main__":
    main()
