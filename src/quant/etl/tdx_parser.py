"""TDX file discovery and symbol mapping helpers.

Binary .day record layout (32 bytes, little-endian) is documented in
docs/data_platform.md §3; the vectorized parser lives in
``quant.etl.staging`` (``DAY_DTYPE`` / ``parse_day_bytes``).
"""

from __future__ import annotations

import re
from pathlib import Path

# filename example: sh600000.day -> symbol = sh600000
_FNAME_RE = re.compile(r"^(sh|sz|bj)(\d{6})\.day$", re.IGNORECASE)


def collect_day_files(root_dir: str | Path) -> list[tuple[Path, str]]:
    """Walk *root_dir* and return [(filepath, symbol), ...] for all .day files."""
    root = Path(root_dir)
    results = []
    for fpath in sorted(root.rglob("*.day")):
        m = _FNAME_RE.match(fpath.name.lower())
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
