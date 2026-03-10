"""Calculate HFQ (后复权) adjustment factors — QUANTAXIS algorithm.

Port of tdx2db/calc/fq_quantaxis.go.

On ex-right dates (GBBQ category 1), the factor is updated:
    ratio = prev_close / preclose_adjusted
    hfq_factor *= ratio

Usage:
    python calc_factor.py

Reads from PostgreSQL (stocks_basic + gbbq) and writes adjust_factor.
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


def _float_equal(a: float, b: float, eps: float = 1e-9) -> bool:
    return abs(a - b) < eps


def calculate_and_insert(conn):
    """Full calculation of HFQ factors from stocks_basic + gbbq."""
    cur = conn.cursor()

    # Load category-1 GBBQ events (ex-right dates per symbol)
    cur.execute(
        f"SELECT symbol, date FROM {SCHEMA}.gbbq WHERE category = 1 ORDER BY symbol, date"
    )
    xdxr_dates: dict[str, set[date]] = defaultdict(set)
    for sym, dt in cur.fetchall():
        xdxr_dates[sym].add(dt)

    # Get all symbols
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
        current_hfq = 1.0
        prev_close = rows[0][1]  # first day close

        for i, (dt, cl, preclose) in enumerate(rows):
            if i > 0 and dt in sym_xdxr:
                if preclose and preclose > 0:
                    ratio = prev_close / preclose
                    if not _float_equal(ratio, 1.0):
                        current_hfq *= ratio

            batch.append((symbol, dt, round(current_hfq, 8)))
            prev_close = cl

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
        f"""INSERT INTO {SCHEMA}.adjust_factor (symbol, date, hfq_factor)
            VALUES %s
            ON CONFLICT (symbol, date) DO UPDATE SET
                hfq_factor = EXCLUDED.hfq_factor""",
        batch,
        page_size=2000,
    )


if __name__ == "__main__":
    conn = get_connection()
    try:
        calculate_and_insert(conn)
    finally:
        conn.close()
