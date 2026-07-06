# FROZEN (v1 legacy): non-runnable since TASK-001; reference only until TASK-033.
"""Calculate pre-close price, change%, amplitude, turnover, and market value.

Port of tdx2db/calc/basic.go — QUANTAXIS-compatible pre-close calculation.

Usage:
    python calc_basic.py

Reads from PostgreSQL (daily_kline + gbbq) and writes stocks_basic.
"""

import sys
import math
from collections import defaultdict
from datetime import date

import psycopg2
import psycopg2.extras

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from quant.db.connection import get_connection
from quant.db.schema import SCHEMA


def _is_share_category(cat: int) -> bool:
    return cat in (2, 3, 5, 7, 8, 9, 10)


def _calculate_preclose(prev_close: float, xdxr: dict | None) -> float:
    """Compute theoretical pre-close on ex-right dates."""
    if xdxr is None:
        return prev_close
    fenhong = xdxr.get("fenhong", 0.0)
    peigu = xdxr.get("peigu", 0.0)
    songzhuangu = xdxr.get("songzhuangu", 0.0)
    peigujia = xdxr.get("peigujia", 0.0)

    denom = 10 + peigu + songzhuangu
    if denom == 0:
        return prev_close
    numer = (prev_close * 10 - fenhong) + (peigu * peigujia)
    return numer / denom


def calculate_and_insert(conn):
    """Full calculation of stocks_basic from daily_kline + gbbq."""
    cur = conn.cursor()

    # Load all GBBQ
    cur.execute(f"SELECT category, symbol, date, c1, c2, c3, c4 FROM {SCHEMA}.gbbq ORDER BY symbol, date")
    gbbq_rows = cur.fetchall()

    gbbq_index = defaultdict(list)
    for cat, sym, dt, c1, c2, c3, c4 in gbbq_rows:
        gbbq_index[sym].append((cat, dt, c1, c2, c3, c4))

    # Get all distinct symbols
    cur.execute(f"SELECT DISTINCT symbol FROM {SCHEMA}.daily_kline ORDER BY symbol")
    symbols = [r[0] for r in cur.fetchall()]

    total = len(symbols)
    batch = []
    BATCH_SIZE = 5000

    for idx, symbol in enumerate(symbols):
        cur.execute(
            f"SELECT date, open, high, low, close, volume, amount "
            f"FROM {SCHEMA}.daily_kline WHERE symbol = %s ORDER BY date",
            (symbol,),
        )
        rows = cur.fetchall()
        if not rows:
            continue

        sym_gbbq = gbbq_index.get(symbol, [])

        # Build xdxr map (category 1 events, keyed by date)
        xdxr_by_date: dict[date, dict] = {}
        for cat, dt, c1, c2, c3, c4 in sym_gbbq:
            if cat == 1:
                if dt not in xdxr_by_date:
                    xdxr_by_date[dt] = {"fenhong": 0, "peigujia": 0, "songzhuangu": 0, "peigu": 0}
                info = xdxr_by_date[dt]
                info["fenhong"] += c1
                info["peigu"] += c2
                info["songzhuangu"] += c3
                if c4 > 0:
                    info["peigujia"] = c4

        # Build shares timeline (categories 2,3,5,7,8,9,10)
        shares_list = sorted(
            [(dt, c3, c4) for cat, dt, c1, c2, c3, c4 in sym_gbbq if _is_share_category(cat)],
            key=lambda x: x[0],
        )

        current_float = 0.0
        current_total = 0.0
        shares_idx = 0

        prev_close = rows[0][4]  # first day close

        for i, (dt, o, h, lo, cl, vol, amt) in enumerate(rows):
            if i == 0:
                preclose = cl
            else:
                xdxr = xdxr_by_date.get(dt)
                preclose = _calculate_preclose(prev_close, xdxr)

            change_pct = 0.0
            amplitude = 0.0
            if preclose > 0:
                change_pct = round((cl - preclose) / preclose * 100, 2)
                amplitude = round((h - lo) / preclose * 100, 2)

            # Advance shares pointer
            while shares_idx < len(shares_list) and shares_list[shares_idx][0] <= dt:
                _, current_float, current_total = shares_list[shares_idx]
                shares_idx += 1

            turnover = 0.0
            floatmv = 0.0
            totalmv = 0.0
            if current_float > 0:
                turnover = round(vol / (current_float * 10000), 6)
                floatmv = round(current_float * 10000 * cl, 2)
            if current_total > 0:
                totalmv = round(current_total * 10000 * cl, 2)

            batch.append((symbol, dt, cl, round(preclose, 4), change_pct, amplitude, turnover, floatmv, totalmv))
            prev_close = cl

            if len(batch) >= BATCH_SIZE:
                _flush_batch(cur, batch)
                batch.clear()

        if (idx + 1) % 500 == 0:
            print(f"  calc_basic: {idx + 1}/{total} symbols processed")

    if batch:
        _flush_batch(cur, batch)

    conn.commit()
    cur.close()
    print(f"  calc_basic: done — {total} symbols")


def _flush_batch(cur, batch):
    psycopg2.extras.execute_values(
        cur,
        f"""INSERT INTO {SCHEMA}.stocks_basic
            (symbol, date, close, preclose, change_pct, amplitude, turnover, floatmv, totalmv)
            VALUES %s
            ON CONFLICT (symbol, date) DO UPDATE SET
                close = EXCLUDED.close,
                preclose = EXCLUDED.preclose,
                change_pct = EXCLUDED.change_pct,
                amplitude = EXCLUDED.amplitude,
                turnover = EXCLUDED.turnover,
                floatmv = EXCLUDED.floatmv,
                totalmv = EXCLUDED.totalmv""",
        batch,
        page_size=2000,
    )


if __name__ == "__main__":
    conn = get_connection()
    try:
        calculate_and_insert(conn)
    finally:
        conn.close()
