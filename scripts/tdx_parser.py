"""Parse TDX binary .day files into (symbol, date, O, H, L, C, volume, amount) tuples.

Binary format: 32 bytes per record, little-endian.
  [0:4]   uint32  date      (YYYYMMDD)
  [4:8]   uint32  open      (×100)
  [8:12]  uint32  high      (×100)
  [12:16] uint32  low       (×100)
  [16:20] uint32  close     (×100)
  [20:24] float32 amount    (IEEE 754)
  [24:28] uint32  volume
  [28:32] (unused)
"""

import struct
import os
import re
from datetime import date
from pathlib import Path

RECORD_FMT = "<IIIIIfII"
RECORD_SIZE = 32

EXCHANGE_MAP = {
    "sh": "sh",
    "sz": "sz",
    "bj": "bj",
}

# filename example: sh600000.day -> symbol = sh600000
_FNAME_RE = re.compile(r"^(sh|sz|bj)(\d{6})\.day$", re.IGNORECASE)


def _parse_date(d: int) -> date | None:
    y, rem = divmod(d, 10000)
    m, day = divmod(rem, 100)
    if y < 1990 or m < 1 or m > 12 or day < 1 or day > 31:
        return None
    try:
        return date(y, m, day)
    except ValueError:
        return None


def parse_day_file(filepath: str | Path, symbol: str) -> list[tuple]:
    """Return list of (symbol, date, open, high, low, close, volume, amount)."""
    filepath = Path(filepath)
    data = filepath.read_bytes()
    n = len(data)
    if n == 0 or n % RECORD_SIZE != 0:
        return []

    rows = []
    for offset in range(0, n, RECORD_SIZE):
        rec = struct.unpack_from(RECORD_FMT, data, offset)
        dt = _parse_date(rec[0])
        if dt is None:
            continue
        rows.append((
            symbol,
            dt,
            rec[1] / 100.0,   # open
            rec[2] / 100.0,   # high
            rec[3] / 100.0,   # low
            rec[4] / 100.0,   # close
            rec[6],            # volume (uint32)
            rec[5],            # amount (float32 -> float)
        ))
    return rows


def collect_day_files(root_dir: str | Path) -> list[tuple[Path, str]]:
    """Walk *root_dir* and return [(filepath, symbol), ...] for all .day files."""
    root = Path(root_dir)
    results = []
    for fpath in sorted(root.rglob("*.day")):
        fname = fpath.name.lower()
        m = _FNAME_RE.match(fname)
        if m:
            symbol = m.group(1).lower() + m.group(2)
            results.append((fpath, symbol))
    return results


def generate_symbol(code: str) -> tuple[str, bool]:
    """Map raw numeric code to exchange-prefixed symbol (matches tdx2db logic)."""
    if len(code) < 2:
        return code, False
    prefix = code[:2]
    if prefix in ("00", "30"):
        return "sz" + code, True
    if prefix in ("60", "68"):
        return "sh" + code, True
    if prefix in ("92", "87", "83", "43"):
        return "bj" + code, True
    return code, False
