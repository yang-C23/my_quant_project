from __future__ import annotations

import argparse
import datetime as dt
import logging

from quant.backtest.engine import run_dualtrend_breath_backtest
from quant.data.loader import list_symbols_from_db, normalize_symbols
from quant.reporting.report import summarize_overall, summarize_results, write_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backtest dual-trend breath selection strategy")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols (e.g. sz000001,sz000002)")
    parser.add_argument("--max-stocks", type=int, default=0, help="Limit number of symbols from DB")
    parser.add_argument("--exclude-boards", default="star", help="Comma-separated boards to exclude")
    parser.add_argument("--start", default="", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default="", help="End date YYYY-MM-DD")

    parser.add_argument("--short-period", type=int, default=10)
    parser.add_argument("--m1", type=int, default=14)
    parser.add_argument("--m2", type=int, default=28)
    parser.add_argument("--m3", type=int, default=57)
    parser.add_argument("--m4", type=int, default=114)
    parser.add_argument("--n-vol", type=int, default=30)
    parser.add_argument("--vol-ratio", type=float, default=3.5)
    parser.add_argument("--setup-window", type=int, default=20)
    parser.add_argument("--kdj-n", type=int, default=9)
    parser.add_argument("--kdj-k", type=int, default=3)
    parser.add_argument("--kdj-d", type=int, default=3)
    parser.add_argument("--j-low", type=float, default=13.0)
    parser.add_argument(
        "--entry-mode",
        default="j_or_zone",
        choices=("j_or_zone", "j_only", "zone_only", "j_and_zone"),
        help="Entry rule for J and price zone",
    )
    parser.add_argument(
        "--entry-require-trend",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require short trend above long trend for entry",
    )
    parser.add_argument(
        "--entry-require-activity",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require volume activity for entry",
    )
    parser.add_argument(
        "--require-pullback",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require pullback with lower volume",
    )
    parser.add_argument(
        "--filter-untradable",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip suspended or limit-up days",
    )
    parser.add_argument(
        "--use-double-vol",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require first double-volume spike",
    )
    parser.add_argument(
        "--require-bullish-setup",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require bullish candle on setup day",
    )
    parser.add_argument("--horizons", default="1,3,5,10,20", help="Forward days, comma-separated")
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

    results = run_dualtrend_breath_backtest(
        symbols=symbols,
        start=start,
        end=end,
        short_period=args.short_period,
        m1=args.m1,
        m2=args.m2,
        m3=args.m3,
        m4=args.m4,
        vol_window=args.n_vol,
        vol_ratio=args.vol_ratio,
        use_double_vol=args.use_double_vol,
        setup_window=args.setup_window,
        require_bullish_setup=args.require_bullish_setup,
        kdj_n=args.kdj_n,
        kdj_k=args.kdj_k,
        kdj_d=args.kdj_d,
        j_low=args.j_low,
        entry_mode=args.entry_mode,
        entry_require_trend=args.entry_require_trend,
        entry_require_activity=args.entry_require_activity,
        require_pullback=args.require_pullback,
        filter_untradable=args.filter_untradable,
        horizons=horizons,
    )

    per_symbol = summarize_results(results, horizons)
    overall = summarize_overall(results, horizons)

    summary = per_symbol
    if not overall.empty:
        summary = overall._append(per_symbol, ignore_index=True)

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"dualtrend_breath_j{args.j_low:g}_vr{args.vol_ratio:g}_{timestamp}"
    outputs = write_report(summary, output_dir=args.output_dir, prefix=prefix)

    print("Report saved:")
    print(f"- {outputs['csv']}")
    print(f"- {outputs['md']}")


if __name__ == "__main__":
    main()
