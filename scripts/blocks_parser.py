"""Parse TDX block/sector metadata files from T0002/hq_cache.

Ported from tdx2db/tdx/blocks.go — handles:
  - needini.dat   → holidays
  - infoharbor_block.dat → concept/style block members
  - tdxhy.cfg     → industry block members
  - tdxzs3.cfg    → block info (name, code, hierarchy)
"""

import csv
import io
import re
from datetime import date
from pathlib import Path


def _read_gbk_file(filepath: str | Path) -> str:
    return Path(filepath).read_bytes().decode("gbk", errors="replace")


# ── Holidays ──────────────────────────────────────────────────────────────────

def parse_holidays(filepath: str | Path) -> list[date]:
    """Parse needini.dat → list of holiday dates."""
    content = Path(filepath).read_text(encoding="utf-8", errors="replace")
    holidays = []
    for line in content.splitlines():
        line = line.strip()
        if not line or not line.startswith("Y") or "=" not in line:
            continue
        _, date_part = line.split("=", 1)
        items = [s.strip() for s in date_part.split(",") if s.strip()]
        if not items:
            continue
        year = items[0]
        for mmdd in items[1:]:
            if len(mmdd) == 4:
                try:
                    holidays.append(date(int(year), int(mmdd[:2]), int(mmdd[2:])))
                except ValueError:
                    continue
    holidays.sort()
    return holidays


# ── Concept / Style block members (infoharbor_block.dat) ──────────────────────

_SECTION_RE = re.compile(r"(?m)^#(GN_|FG_|ZS_)")

_EXCHANGE_PREFIX = {"0": "sz", "1": "sh", "2": "bj"}


def parse_infoharbor_blocks(filepath: str | Path) -> list[tuple[str, str]]:
    """Parse infoharbor_block.dat → list of (stock_symbol, block_code)."""
    content = _read_gbk_file(filepath)
    matches = list(_SECTION_RE.finditer(content))
    if not matches:
        return []

    sections = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        sections.append(content[start:end])

    block_type_map = {"GN": "gn", "FG": "fg"}
    results = []

    for section in sections:
        section = section.strip()
        if not section:
            continue
        prefix2 = section[1:3]
        if prefix2 not in block_type_map:
            continue

        lines = section.split("\n")
        if not lines:
            continue

        header_parts = lines[0].split(",")
        if len(header_parts) < 3:
            continue

        header_first = header_parts[0].lstrip("#")
        code_parts = header_first.split("_", 1)
        if len(code_parts) < 2:
            continue
        block_code = code_parts[1]

        all_codes = "".join(lines[1:])
        for raw in all_codes.split(","):
            raw = raw.strip()
            if "#" not in raw:
                continue
            parts = raw.split("#")
            if len(parts) != 2:
                continue
            ex_prefix = _EXCHANGE_PREFIX.get(parts[0])
            if ex_prefix:
                results.append((ex_prefix + parts[1], block_code))

    return results


# ── Industry block members (tdxhy.cfg) ────────────────────────────────────────

def parse_tdxhy(filepath: str | Path) -> list[tuple[str, str]]:
    """Parse tdxhy.cfg → list of (stock_symbol, block_code)."""
    content = Path(filepath).read_bytes().decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(content), delimiter="|")
    results = []

    for record in reader:
        if len(record) < 6:
            continue
        exchange, code = record[0], record[1]
        tdxhy_t, tdxhy_x = record[2], record[5] if len(record) > 5 else ""

        if exchange == "0" and code.startswith("20"):
            continue

        prefix = _EXCHANGE_PREFIX.get(exchange)
        if not prefix:
            continue
        stock_symbol = prefix + code

        if tdxhy_t:
            results.append((stock_symbol, tdxhy_t))
        if tdxhy_x:
            results.append((stock_symbol, tdxhy_x))

    return results


# ── Block info (tdxzs3.cfg) ───────────────────────────────────────────────────

_TYPE_MAP = {
    "2": "tdx_general",
    "3": "region",
    "4": "concept",
    "5": "style",
    "12": "tdx_research",
}


def parse_tdxzs3(filepath: str | Path) -> list[tuple]:
    """Parse tdxzs3.cfg → list of (block_type, block_name, block_symbol, block_code, parent_code, block_level)."""
    raw = Path(filepath).read_bytes().decode("gbk", errors="replace")
    reader = csv.reader(io.StringIO(raw), delimiter="|")
    results = []

    for record in reader:
        if len(record) < 6:
            continue
        blk_name = record[0]
        blk_code = record[1]
        blk_type_raw = record[2]
        blk_label = record[5].strip()

        block_symbol = "sh" + blk_code
        parent_code = ""
        block_level = 1

        label_len = len(blk_label)
        if blk_type_raw == "12":
            if label_len == 5:
                parent_code = blk_label[:3]
                block_level = 2
            elif label_len == 7:
                parent_code = blk_label[:5]
                block_level = 3
        elif blk_type_raw == "2":
            if label_len == 7:
                parent_code = blk_label[:5]
                block_level = 2

        block_type = _TYPE_MAP.get(blk_type_raw, blk_type_raw)

        results.append((block_type, blk_name, block_symbol, blk_label, parent_code, block_level))

    return results
