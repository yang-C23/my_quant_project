#!/usr/bin/env python3
"""Incremental daily update: sync TDX vipdoc → PostgreSQL.

Reads .day files from the TDX vipdoc directory (maintained by TDX software),
imports only new records after the latest date in the database, then
recalculates GBBQ, stocks_basic, and adjustment factors.

Usage:
    # After running TDX and downloading latest data:
    python scripts/update_daily.py
    python scripts/update_daily.py --vipdoc /mnt/d/new_tdx/vipdoc --tdxhome /mnt/d/new_tdx
"""

import argparse
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import psycopg2
import psycopg2.extras

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from quant.db.connection import get_connection
from quant.db.schema import SCHEMA, create_views

from tdx_parser import parse_day_file, collect_day_files
from gbbq_decoder import decode_gbbq_file
from blocks_parser import parse_holidays, parse_infoharbor_blocks, parse_tdxhy, parse_tdxzs3
from calc_basic import calculate_and_insert as calc_basic
from calc_factor import calculate_and_insert as calc_factor

BATCH_SIZE = 5000


def get_latest_date(conn) -> date | None:
    cur = conn.cursor()
    cur.execute(f"SELECT MAX(date) FROM {SCHEMA}.daily_kline")
    row = cur.fetchone()
    cur.close()
    return row[0] if row and row[0] else None


def update_kline(conn, vipdoc_dir: str):
    """Incrementally import new K-line data from vipdoc .day files."""
    latest = get_latest_date(conn)
    print(f"[kline] Latest date in DB: {latest}")

    files = collect_day_files(vipdoc_dir)
    print(f"[kline] Found {len(files)} .day files in {vipdoc_dir}")

    cur = conn.cursor()
    new_rows = 0
    batch = []

    for i, (fpath, symbol) in enumerate(files):
        rows = parse_day_file(fpath, symbol)
        if latest:
            rows = [r for r in rows if r[1] > latest]
        batch.extend(rows)

        if len(batch) >= BATCH_SIZE:
            _insert_batch(cur, batch)
            new_rows += len(batch)
            batch.clear()

        if (i + 1) % 2000 == 0:
            conn.commit()
            print(f"  {i + 1}/{len(files)} files scanned, {new_rows:,} new rows")

    if batch:
        _insert_batch(cur, batch)
        new_rows += len(batch)

    conn.commit()
    cur.close()
    print(f"[kline] Incremental import done — {new_rows:,} new rows")
    return new_rows


def _insert_batch(cur, batch):
    psycopg2.extras.execute_values(
        cur,
        f"""INSERT INTO {SCHEMA}.daily_kline
            (symbol, date, open, high, low, close, volume, amount)
            VALUES %s
            ON CONFLICT (symbol, date) DO NOTHING""",
        batch,
        page_size=2000,
    )


def update_gbbq(conn, tdxhome: str):
    """Re-import GBBQ from TDX."""
    gbbq_path = Path(tdxhome) / "T0002" / "hq_cache" / "gbbq"
    if not gbbq_path.exists():
        print(f"[gbbq] GBBQ file not found at {gbbq_path}")
        return

    cur = conn.cursor()
    cur.execute(f"TRUNCATE TABLE {SCHEMA}.gbbq")
    records = decode_gbbq_file(str(gbbq_path))
    print(f"[gbbq] Decoded {len(records):,} records")

    for i in range(0, len(records), BATCH_SIZE):
        psycopg2.extras.execute_values(
            cur,
            f"INSERT INTO {SCHEMA}.gbbq (category, symbol, date, c1, c2, c3, c4) VALUES %s",
            records[i:i + BATCH_SIZE],
            page_size=2000,
        )
    conn.commit()
    cur.close()


def update_securities(conn):
    """Update securities master table."""
    cur = conn.cursor()
    cur.execute(f"""
        INSERT INTO {SCHEMA}.securities (symbol, code, exchange, sec_type, listing_date)
        SELECT
            symbol,
            SUBSTRING(symbol FROM 3) AS code,
            SUBSTRING(symbol FROM 1 FOR 2) AS exchange,
            CASE
                WHEN symbol ~ '^(sh000|sz399|bj899)' THEN 'index'
                WHEN symbol ~ '^(sh51|sz15|sz16)' THEN 'etf'
                ELSE 'stock'
            END AS sec_type,
            MIN(date) AS listing_date
        FROM {SCHEMA}.daily_kline
        GROUP BY symbol
        ON CONFLICT (symbol) DO UPDATE SET
            listing_date = LEAST({SCHEMA}.securities.listing_date, EXCLUDED.listing_date)
    """)
    cur.execute(f"""
        UPDATE {SCHEMA}.securities SET board = CASE
            WHEN code LIKE '60%%' THEN 'main'
            WHEN code LIKE '00%%' THEN 'main'
            WHEN code LIKE '30%%' THEN 'chinext'
            WHEN code LIKE '68%%' THEN 'star'
            WHEN exchange = 'bj'   THEN 'bse'
            ELSE 'other'
        END WHERE sec_type = 'stock'
    """)
    conn.commit()
    cur.close()


def update_blocks(conn, tdxhome: str):
    """Re-import block metadata."""
    hq_cache = Path(tdxhome) / "T0002" / "hq_cache"
    cur = conn.cursor()

    holidays_file = hq_cache / "needini.dat"
    if holidays_file.exists():
        holidays = parse_holidays(str(holidays_file))
        cur.execute(f"TRUNCATE TABLE {SCHEMA}.holidays")
        if holidays:
            psycopg2.extras.execute_values(
                cur,
                f"INSERT INTO {SCHEMA}.holidays (date) VALUES %s ON CONFLICT DO NOTHING",
                [(h,) for h in holidays],
            )

    zs3_file = hq_cache / "tdxzs3.cfg"
    if zs3_file.exists():
        block_infos = parse_tdxzs3(str(zs3_file))
        cur.execute(f"TRUNCATE TABLE {SCHEMA}.blocks_info")
        if block_infos:
            psycopg2.extras.execute_values(
                cur,
                f"""INSERT INTO {SCHEMA}.blocks_info
                    (block_type, block_name, block_symbol, block_code, parent_code, block_level)
                    VALUES %s""",
                block_infos, page_size=2000,
            )

    members = []
    info_file = hq_cache / "infoharbor_block.dat"
    if info_file.exists():
        members.extend(parse_infoharbor_blocks(str(info_file)))
    hy_file = hq_cache / "tdxhy.cfg"
    if hy_file.exists():
        members.extend(parse_tdxhy(str(hy_file)))
    if members:
        cur.execute(f"TRUNCATE TABLE {SCHEMA}.blocks_member")
        psycopg2.extras.execute_values(
            cur,
            f"INSERT INTO {SCHEMA}.blocks_member (stock_symbol, block_code) VALUES %s",
            members, page_size=2000,
        )

    conn.commit()
    cur.close()


def print_summary(conn):
    cur = conn.cursor()
    tables = [
        "securities", "daily_kline", "gbbq", "stocks_basic",
        "adjust_factor", "blocks_info", "blocks_member", "holidays",
    ]
    print("\n" + "=" * 50)
    print("Table summary:")
    for t in tables:
        cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.{t}")
        print(f"  {SCHEMA}.{t:20s} {cur.fetchone()[0]:>12,} rows")
    print("=" * 50)
    cur.close()


def main():
    parser = argparse.ArgumentParser(description="Incremental daily update from TDX vipdoc")
    parser.add_argument("--vipdoc", default="/mnt/d/new_tdx/vipdoc", help="TDX vipdoc directory")
    parser.add_argument("--tdxhome", default="/mnt/d/new_tdx", help="TDX installation directory")
    parser.add_argument("--dsn", default=None, help="PostgreSQL DSN")
    parser.add_argument("--skip-calc", action="store_true", help="Skip basic/factor recalculation")
    args = parser.parse_args()

    if args.dsn:
        os.environ["QUANT_DB_DSN"] = args.dsn

    conn = get_connection()
    t0 = time.time()

    try:
        new_rows = update_kline(conn, args.vipdoc)

        if new_rows > 0 or True:
            update_gbbq(conn, args.tdxhome)
            update_securities(conn)
            update_blocks(conn, args.tdxhome)

            if not args.skip_calc:
                print("[basic] Recalculating stocks_basic ...")
                calc_basic(conn)
                print("[factor] Recalculating adjustment factors ...")
                calc_factor(conn)

            create_views(conn)

        print_summary(conn)
    finally:
        conn.close()

    print(f"\nTotal time: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
