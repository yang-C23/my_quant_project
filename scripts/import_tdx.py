#!/usr/bin/env python3
"""Main orchestrator: unzip TDX data → parse → import to PostgreSQL → calculate factors.

Usage:
    python scripts/import_tdx.py --zip /mnt/d/TDX_hsjday.zip --tdxhome /mnt/d/new_tdx

Steps:
  1. init     — create schema + tables
  2. kline    — unzip & parse .day files → daily_kline
  3. gbbq     — decode GBBQ → gbbq table
  4. blocks   — parse block metadata → blocks_info, blocks_member, holidays
  5. basic    — calculate preclose, turnover, market-value → stocks_basic
  6. factor   — calculate HFQ adjustment factors → adjust_factor
  7. views    — create v_bfq_daily, v_qfq_daily, v_hfq_daily
  8. securities — populate securities master table from kline + blocks data
"""

import argparse
import os
import sys
import time
import tempfile
import zipfile
from pathlib import Path
from datetime import date

import psycopg2
import psycopg2.extras

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from quant.db.connection import get_connection
from quant.db.schema import SCHEMA, init_schema, create_views

from tdx_parser import parse_day_file, collect_day_files
from gbbq_decoder import decode_gbbq_file
from blocks_parser import parse_holidays, parse_infoharbor_blocks, parse_tdxhy, parse_tdxzs3
from calc_basic import calculate_and_insert as calc_basic
from calc_factor import calculate_and_insert as calc_factor


BATCH_SIZE = 5000


def step_init(conn):
    """Create schema, tables, indexes."""
    print("[1/8] Initializing database schema ...")
    init_schema(conn)
    print("  Schema and tables created.")


def step_kline(conn, zip_path: str | None, day_dir: str | None):
    """Import daily K-line data from .day files."""
    print("[2/8] Importing daily K-line data ...")

    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.daily_kline")
    existing = cur.fetchone()[0]
    if existing > 0:
        print(f"  daily_kline already has {existing:,} rows — skipping import.")
        cur.close()
        return

    if zip_path and Path(zip_path).exists():
        tmpdir = tempfile.mkdtemp(prefix="tdx_day_")
        print(f"  Extracting {zip_path} → {tmpdir} ...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmpdir)
        # Handle nested backslash paths from Windows zip
        _fix_backslash_paths(tmpdir)
        source_dir = tmpdir
    elif day_dir and Path(day_dir).exists():
        source_dir = day_dir
    else:
        print("  ERROR: No valid zip or day directory provided.")
        cur.close()
        return

    files = collect_day_files(source_dir)
    print(f"  Found {len(files)} .day files")

    batch = []
    total_rows = 0

    for i, (fpath, symbol) in enumerate(files):
        rows = parse_day_file(fpath, symbol)
        batch.extend(rows)

        if len(batch) >= BATCH_SIZE:
            _insert_kline_batch(cur, batch)
            total_rows += len(batch)
            batch.clear()

        if (i + 1) % 1000 == 0:
            conn.commit()
            print(f"  {i + 1}/{len(files)} files processed, {total_rows:,} rows inserted")

    if batch:
        _insert_kline_batch(cur, batch)
        total_rows += len(batch)

    conn.commit()
    cur.close()
    print(f"  daily_kline import done — {total_rows:,} rows from {len(files)} files")


def _fix_backslash_paths(directory: str):
    """Rename files with backslash-encoded paths (from Windows zip on Linux)."""
    root = Path(directory)
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        if "\\" in f.name:
            new_name = f.name.split("\\")[-1]
            new_path = f.parent / new_name
            if not new_path.exists():
                f.rename(new_path)


def _insert_kline_batch(cur, batch):
    psycopg2.extras.execute_values(
        cur,
        f"""INSERT INTO {SCHEMA}.daily_kline
            (symbol, date, open, high, low, close, volume, amount)
            VALUES %s
            ON CONFLICT (symbol, date) DO NOTHING""",
        batch,
        page_size=2000,
    )


def step_gbbq(conn, tdxhome: str):
    """Decode and import GBBQ data."""
    print("[3/8] Decoding and importing GBBQ ...")

    gbbq_path = Path(tdxhome) / "T0002" / "hq_cache" / "gbbq"
    if not gbbq_path.exists():
        print(f"  ERROR: GBBQ file not found at {gbbq_path}")
        return

    cur = conn.cursor()

    # Truncate and re-import (GBBQ is a full snapshot)
    cur.execute(f"TRUNCATE TABLE {SCHEMA}.gbbq")

    records = decode_gbbq_file(str(gbbq_path))
    print(f"  Decoded {len(records):,} GBBQ records")

    batch = []
    for rec in records:
        batch.append(rec)
        if len(batch) >= BATCH_SIZE:
            psycopg2.extras.execute_values(
                cur,
                f"""INSERT INTO {SCHEMA}.gbbq (category, symbol, date, c1, c2, c3, c4)
                    VALUES %s""",
                batch,
                page_size=2000,
            )
            batch.clear()

    if batch:
        psycopg2.extras.execute_values(
            cur,
            f"""INSERT INTO {SCHEMA}.gbbq (category, symbol, date, c1, c2, c3, c4)
                VALUES %s""",
            batch,
            page_size=2000,
        )

    conn.commit()
    cur.close()
    print(f"  GBBQ import done — {len(records):,} records")


def step_blocks(conn, tdxhome: str):
    """Parse and import block metadata, block members, and holidays."""
    print("[4/8] Importing block metadata ...")
    hq_cache = Path(tdxhome) / "T0002" / "hq_cache"
    cur = conn.cursor()

    # Holidays
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
        print(f"  Holidays: {len(holidays)} dates")
    else:
        print("  needini.dat not found — skipping holidays")

    # Block info (tdxzs3.cfg)
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
                block_infos,
                page_size=2000,
            )
        print(f"  Block info: {len(block_infos)} entries")
    else:
        print("  tdxzs3.cfg not found — skipping block info")

    # Block members: concept/style (infoharbor_block.dat)
    members_all = []
    info_file = hq_cache / "infoharbor_block.dat"
    if info_file.exists():
        concept_members = parse_infoharbor_blocks(str(info_file))
        members_all.extend(concept_members)
        print(f"  Concept/style members: {len(concept_members)}")
    else:
        print("  infoharbor_block.dat not found")

    # Block members: industry (tdxhy.cfg)
    hy_file = hq_cache / "tdxhy.cfg"
    if hy_file.exists():
        industry_members = parse_tdxhy(str(hy_file))
        members_all.extend(industry_members)
        print(f"  Industry members: {len(industry_members)}")
    else:
        print("  tdxhy.cfg not found")

    if members_all:
        cur.execute(f"TRUNCATE TABLE {SCHEMA}.blocks_member")
        psycopg2.extras.execute_values(
            cur,
            f"""INSERT INTO {SCHEMA}.blocks_member (stock_symbol, block_code)
                VALUES %s""",
            members_all,
            page_size=2000,
        )

    conn.commit()
    cur.close()
    print(f"  Block members total: {len(members_all)}")


def step_securities(conn):
    """Populate the securities master table from existing kline data."""
    print("[5/8] Populating securities master table ...")
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

    # Infer board classification
    cur.execute(f"""
        UPDATE {SCHEMA}.securities SET board = CASE
            WHEN code LIKE '60%%' THEN 'main'
            WHEN code LIKE '00%%' THEN 'main'
            WHEN code LIKE '30%%' THEN 'chinext'
            WHEN code LIKE '68%%' THEN 'star'
            WHEN exchange = 'bj'   THEN 'bse'
            ELSE 'other'
        END
        WHERE sec_type = 'stock'
    """)

    conn.commit()
    cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.securities")
    count = cur.fetchone()[0]
    cur.close()
    print(f"  Securities: {count} entries")


def step_basic(conn):
    """Calculate pre-close, turnover, market value."""
    print("[6/8] Calculating stocks_basic ...")
    calc_basic(conn)


def step_factor(conn):
    """Calculate HFQ adjustment factors."""
    print("[7/8] Calculating adjustment factors ...")
    calc_factor(conn)


def step_views(conn):
    """Create views for forward/backward adjusted prices."""
    print("[8/8] Creating views ...")
    create_views(conn)
    print("  Views created: v_bfq_daily, v_qfq_daily, v_hfq_daily")


def print_summary(conn):
    """Print final table statistics."""
    cur = conn.cursor()
    tables = [
        "securities", "daily_kline", "gbbq", "stocks_basic",
        "adjust_factor", "blocks_info", "blocks_member", "holidays",
    ]
    print("\n" + "=" * 50)
    print("Table summary:")
    print("-" * 50)
    for t in tables:
        cur.execute(f"SELECT COUNT(*) FROM {SCHEMA}.{t}")
        count = cur.fetchone()[0]
        print(f"  {SCHEMA}.{t:20s} {count:>12,} rows")

    # Check views
    for v in ["v_bfq_daily", "v_qfq_daily", "v_hfq_daily"]:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.views WHERE table_schema = %s AND table_name = %s)",
            (SCHEMA, v),
        )
        exists = cur.fetchone()[0]
        print(f"  {SCHEMA}.{v:20s} {'✓ exists' if exists else '✗ missing'}")

    print("=" * 50)
    cur.close()


def main():
    parser = argparse.ArgumentParser(description="Import TDX data into PostgreSQL")
    parser.add_argument("--zip", default="/mnt/d/TDX_hsjday.zip", help="Path to hsjday.zip")
    parser.add_argument("--daydir", default=None, help="Alternative: directory with .day files")
    parser.add_argument("--tdxhome", default="/mnt/d/new_tdx", help="TDX installation directory")
    parser.add_argument("--dsn", default=None, help="PostgreSQL DSN (overrides env/default)")
    parser.add_argument(
        "--steps",
        default="all",
        help="Comma-separated steps to run: init,kline,gbbq,blocks,securities,basic,factor,views (default: all)",
    )
    args = parser.parse_args()

    if args.dsn:
        os.environ["QUANT_DB_DSN"] = args.dsn

    conn = get_connection()
    t0 = time.time()

    try:
        steps = args.steps.split(",") if args.steps != "all" else [
            "init", "kline", "gbbq", "blocks", "securities", "basic", "factor", "views"
        ]

        if "init" in steps:
            step_init(conn)
        if "kline" in steps:
            step_kline(conn, args.zip, args.daydir)
        if "gbbq" in steps:
            step_gbbq(conn, args.tdxhome)
        if "blocks" in steps:
            step_blocks(conn, args.tdxhome)
        if "securities" in steps:
            step_securities(conn)
        if "basic" in steps:
            step_basic(conn)
        if "factor" in steps:
            step_factor(conn)
        if "views" in steps:
            step_views(conn)

        print_summary(conn)

    finally:
        conn.close()

    elapsed = time.time() - t0
    print(f"\nTotal time: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
