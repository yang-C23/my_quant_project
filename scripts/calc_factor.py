"""Calculate adjustment factors — HFQ (QUANTAXIS) + QFQ (TDX subtractive).

HFQ factor (后复权因子):
    Multiplicative factor from the QUANTAXIS algorithm.
    On ex-right dates: ratio = prev_close / preclose_adjusted
    hfq_factor *= ratio

QFQ parameters (前复权, TDX-style):
    QFQ_price = raw_price * qfq_scale - qfq_offset
    For each future ex-rights event (latest to earliest):
        scale = scale / (1 + stock_div_ratio)
        offset = offset + cash_div_per_share * scale
    Pure cash dividends: scale=1, offset=sum(future divs per share).

Usage:
    python calc_factor.py
"""

import sys
from collections import defaultdict
from datetime import date

import psycopg2
import psycopg2.extras

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from quant.db.connection import get_connection
from quant.db.schema import SCHEMA


def _float_equal(a: float, b: float, eps: float = 1e-9) -> bool:
    return abs(a - b) < eps


def calculate_and_insert(conn):
    cur = conn.cursor()

    cur.execute(
        f"SELECT symbol, date, c1, c3, c4 FROM {SCHEMA}.gbbq "
        f"WHERE category = 1 ORDER BY symbol, date"
    )
    gbbq_events: dict[str, list[tuple]] = defaultdict(list)
    xdxr_dates: dict[str, set[date]] = defaultdict(set)
    for sym, dt, c1, c3, c4 in cur.fetchall():
        cash_div = c1 / 10.0   # 每股现金分红
        stock_div = c3 / 10.0  # 每股送转比例
        gbbq_events[sym].append((dt, cash_div, stock_div))
        xdxr_dates[sym].add(dt)

    cur.execute(f"SELECT DISTINCT symbol FROM {SCHEMA}.stocks_basic ORDER BY symbol")
    symbols = [r[0] for r in cur.fetchall()]

    total = len(symbols)
    batch = []
    BATCH_SIZE = 5000

    for idx, symbol in enumerate(symbols):
        cur.execute(
            f"SELECT date, close, preclose FROM {SCHEMA}.stocks_basic "
            f"WHERE symbol = %s ORDER BY date",
            (symbol,),
        )
        rows = cur.fetchall()
        if not rows:
            continue

        sym_xdxr = xdxr_dates.get(symbol, set())
        events = gbbq_events.get(symbol, [])

        # --- HFQ factor (multiplicative, QUANTAXIS) ---
        current_hfq = 1.0
        prev_close = rows[0][1]
        hfq_by_date = {}
        for i, (dt, cl, preclose) in enumerate(rows):
            if i > 0 and dt in sym_xdxr:
                if preclose and preclose > 0:
                    ratio = prev_close / preclose
                    if not _float_equal(ratio, 1.0):
                        current_hfq *= ratio
            hfq_by_date[dt] = round(current_hfq, 8)
            prev_close = cl

        # --- QFQ parameters (subtractive, TDX-style) ---
        # For each trading date, compute (scale, offset) from all future events.
        # Process events from latest to earliest:
        #   scale  = scale / (1 + stock_div)
        #   offset = offset + cash_div * scale
        all_dates = [r[0] for r in rows]
        sorted_events = sorted(events, key=lambda e: e[0])

        qfq_params: dict[date, tuple[float, float]] = {}
        scale = 1.0
        offset = 0.0
        ev_idx = len(sorted_events) - 1

        for dt in reversed(all_dates):
            while ev_idx >= 0 and sorted_events[ev_idx][0] > dt:
                _, cash_div, stock_div = sorted_events[ev_idx]
                scale = scale / (1.0 + stock_div)
                offset = offset + cash_div * scale
                ev_idx -= 1
            qfq_params[dt] = (round(scale, 10), round(offset, 6))

        for dt in all_dates:
            s, o = qfq_params[dt]
            batch.append((symbol, dt, hfq_by_date[dt], s, o))
            if len(batch) >= BATCH_SIZE:
                _flush_batch(cur, batch)
                batch.clear()

        if (idx + 1) % 500 == 0:
            print(f"  calc_factor: {idx + 1}/{total} symbols processed")

    if batch:
        _flush_batch(cur, batch)

    conn.commit()
    cur.close()
    print(f"  calc_factor: done — {total} symbols")


def _flush_batch(cur, batch):
    psycopg2.extras.execute_values(
        cur,
        f"""INSERT INTO {SCHEMA}.adjust_factor (symbol, date, hfq_factor, qfq_scale, qfq_offset)
            VALUES %s
            ON CONFLICT (symbol, date) DO UPDATE SET
                hfq_factor = EXCLUDED.hfq_factor,
                qfq_scale  = EXCLUDED.qfq_scale,
                qfq_offset = EXCLUDED.qfq_offset""",
        batch,
        page_size=2000,
    )


if __name__ == "__main__":
    conn = get_connection()
    try:
        calculate_and_insert(conn)
    finally:
        conn.close()
