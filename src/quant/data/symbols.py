"""Symbol normalization helpers for internal and qlib conventions."""

from __future__ import annotations

import re

_CN_RE = re.compile(r"^(sh|sz|bj)\d{6}$")
_QLIB_CN_RE = re.compile(r"^(SH|SZ|BJ)\d{6}$")


def to_qlib(symbol: str) -> str:
    """Convert an internal symbol to qlib instrument format."""
    value = str(symbol).strip()
    lower = value.lower()
    if lower.startswith("us:"):
        return value.split(":", 1)[1].upper()
    if not _CN_RE.match(lower):
        raise ValueError(f"invalid internal symbol: {symbol!r}")
    return lower[:2].upper() + lower[2:]


def from_qlib(instrument: str) -> str:
    """Convert a qlib instrument to internal symbol format."""
    value = str(instrument).strip()
    upper = value.upper()
    if _QLIB_CN_RE.match(upper):
        return upper[:2].lower() + upper[2:]
    if not value:
        raise ValueError("instrument must be non-empty")
    return f"us:{upper}"


def exchange_of(symbol: str) -> str:
    """Return the exchange code: sh, sz, bj, or us."""
    value = str(symbol).strip().lower()
    if value.startswith("us:"):
        return "us"
    if not _CN_RE.match(value):
        raise ValueError(f"invalid internal symbol: {symbol!r}")
    return value[:2]


def board_of(symbol: str) -> str:
    """Infer the local security board from exchange and prefix rules."""
    value = str(symbol).strip().lower()
    exchange = exchange_of(value)
    if exchange == "us":
        return "us"
    code = value[2:]

    if exchange == "sh" and code.startswith(("000", "999")):
        return "index"
    if exchange == "sz" and code.startswith("399"):
        return "index"
    if exchange == "bj" and code.startswith("899"):
        return "index"
    if exchange == "sh" and code.startswith(("880", "881", "887", "888")):
        return "index"
    if exchange == "sh" and code.startswith(("110", "113", "118")):
        return "bond"
    if exchange == "sz" and code.startswith(("123", "127", "128")):
        return "bond"
    if exchange == "sh" and code.startswith(("50", "51", "56", "58")):
        return "etf"
    if exchange == "sz" and code.startswith(("15", "16")):
        return "etf"
    if exchange == "sh" and code.startswith("900"):
        return "b"
    if exchange == "sz" and code.startswith("200"):
        return "b"
    if exchange == "bj" or code.startswith(("43", "83", "87", "920")):
        return "bse"
    if code.startswith(("300", "301")):
        return "gem"
    if code.startswith(("688", "689")):
        return "star"
    if exchange == "sh" and code.startswith(("600", "601", "603", "605")):
        return "main"
    if exchange == "sz" and code.startswith(("000", "001", "002", "003")):
        return "main"
    return "other"
