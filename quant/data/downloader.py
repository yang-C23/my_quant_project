from __future__ import annotations

import argparse
import datetime as dt
import logging
import random
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional
import os

import pandas as pd
import tushare as ts
from tqdm import tqdm

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_FILE = PROJECT_ROOT / "download.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"),
    ],
)
LOGGER = logging.getLogger("download_kline")

COOLDOWN_SECS = 600
BAN_PATTERNS = (
    "访问频繁",
    "请稍后",
    "超过频率",
    "频繁访问",
    "too many requests",
    "429",
    "forbidden",
    "403",
    "max retries exceeded",
)


class RateLimitError(RuntimeError):
    pass


def _load_token_from_csv(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
        if "token" in df.columns and not df.empty:
            token = str(df["token"].dropna().iloc[0]).strip()
            return token or None
    except Exception:
        pass

    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.lower() == "token":
                continue
            return line
    except Exception:
        return None
    return None


def _looks_like_ip_ban(exc: Exception) -> bool:
    msg = (str(exc) or "").lower()
    return any(pat in msg for pat in BAN_PATTERNS)


def _cool_sleep(base_seconds: int) -> None:
    jitter = random.uniform(0.9, 1.2)
    sleep_s = max(1, int(base_seconds * jitter))
    LOGGER.warning("Rate limit detected. Cooling down for %d seconds", sleep_s)
    time.sleep(sleep_s)


def _to_ts_code(code: str) -> str:
    code = str(code).zfill(6)
    if code.startswith(("60", "68", "9")):
        return f"{code}.SH"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def _get_raw_kline_tushare(
    code: str,
    start: str,
    end: str,
    api: ts.pro_api,
) -> pd.DataFrame:
    ts_code = _to_ts_code(code)
    try:
        df = ts.pro_bar(
            ts_code=ts_code,
            adj=None,
            start_date=start,
            end_date=end,
            freq="D",
            api=api,
        )
    except Exception as exc:
        if _looks_like_ip_ban(exc):
            raise RateLimitError(str(exc)) from exc
        raise

    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    if df.empty:
        return pd.DataFrame()

    df = df.rename(columns={"trade_date": "date", "vol": "volume"})[
        ["date", "open", "close", "high", "low", "volume"]
    ].copy()
    df["date"] = pd.to_datetime(df["date"])
    for c in ["open", "close", "high", "low", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def _get_adj_factor_tushare(
    code: str,
    start: str,
    end: str,
    api: ts.pro_api,
) -> pd.DataFrame:
    ts_code = _to_ts_code(code)
    try:
        df = api.adj_factor(ts_code=ts_code, start_date=start, end_date=end)
    except Exception as exc:
        if _looks_like_ip_ban(exc):
            raise RateLimitError(str(exc)) from exc
        raise

    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    if df.empty:
        return pd.DataFrame()

    df = df.rename(columns={"trade_date": "date", "adj_factor": "factor"})[
        ["date", "factor"]
    ].copy()
    df["date"] = pd.to_datetime(df["date"])
    df["factor"] = pd.to_numeric(df["factor"], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def validate(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df = df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    if df["date"].isna().any():
        raise ValueError("Missing dates detected")
    if (df["date"] > pd.Timestamp.today()).any():
        raise ValueError("Future dates detected")
    return df


def validate_factor(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    df = df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    if df["date"].isna().any():
        raise ValueError("Missing dates detected")
    if (df["date"] > pd.Timestamp.today()).any():
        raise ValueError("Future dates detected")
    if df["factor"].isna().any():
        raise ValueError("Missing adj_factor detected")
    return df


def _last_date(path: Path) -> pd.Timestamp | None:
    if not path.exists():
        return None
    try:
        dates = pd.read_csv(path, usecols=["date"])
    except Exception:
        return None
    if dates.empty or "date" not in dates.columns:
        return None
    last = pd.to_datetime(dates["date"], errors="coerce").max()
    return last if pd.notna(last) else None


def _filter_by_boards_stocklist(df: pd.DataFrame, exclude_boards: set[str]) -> pd.DataFrame:
    if "symbol" in df.columns:
        code = df["symbol"].astype(str)
    elif "ts_code" in df.columns:
        code = df["ts_code"].astype(str).str.split(".").str[0]
    else:
        return df

    ts_code = df["ts_code"].astype(str).str.upper() if "ts_code" in df.columns else code
    mask = pd.Series(True, index=df.index)

    if "gem" in exclude_boards:
        mask &= ~code.str.startswith(("300", "301"))
    if "star" in exclude_boards:
        mask &= ~code.str.startswith(("688",))
    if "bj" in exclude_boards:
        mask &= ~(ts_code.str.endswith(".BJ") | code.str.startswith(("4", "8")))

    return df[mask].copy()


def load_codes_from_stocklist(stocklist_csv: Path, exclude_boards: set[str]) -> list[str]:
    df = pd.read_csv(stocklist_csv)
    df = _filter_by_boards_stocklist(df, exclude_boards)
    if "symbol" in df.columns:
        codes = df["symbol"].astype(str).str.zfill(6).tolist()
    elif "ts_code" in df.columns:
        codes = df["ts_code"].astype(str).str.split(".").str[0].str.zfill(6).tolist()
    else:
        raise ValueError("stocklist.csv must contain 'symbol' or 'ts_code' column")
    codes = list(dict.fromkeys(codes))
    LOGGER.info(
        "Loaded %d symbols from %s (excluded: %s)",
        len(codes),
        stocklist_csv,
        ",".join(sorted(exclude_boards)) or "none",
    )
    return codes


def fetch_one(
    code: str,
    start: str,
    end: str,
    raw_dir: Path,
    factor_dir: Path,
    overwrite: bool,
    api: ts.pro_api,
) -> tuple[str, bool]:
    raw_path = raw_dir / f"{code}.csv"
    factor_path = factor_dir / f"{code}.csv"

    raw_existing = pd.DataFrame()
    factor_existing = pd.DataFrame()
    raw_last = None
    factor_last = None

    if raw_path.exists() and not overwrite:
        try:
            raw_existing = pd.read_csv(raw_path)
            if "date" in raw_existing.columns and not raw_existing.empty:
                raw_existing["date"] = pd.to_datetime(raw_existing["date"], errors="coerce")
                raw_last = raw_existing["date"].max()
        except Exception as exc:
            LOGGER.warning("%s raw incremental read failed (%s), falling back to full download", code, exc)
            overwrite = True

    if factor_path.exists() and not overwrite:
        try:
            factor_existing = pd.read_csv(factor_path)
            if "date" in factor_existing.columns and not factor_existing.empty:
                factor_existing["date"] = pd.to_datetime(factor_existing["date"], errors="coerce")
                factor_last = factor_existing["date"].max()
        except Exception as exc:
            LOGGER.warning("%s factor incremental read failed (%s), falling back to full download", code, exc)
            overwrite = True

    end_dt = pd.to_datetime(end)
    if raw_last is not None and factor_last is not None and end_dt <= raw_last and end_dt <= factor_last:
        return code, True

    for attempt in range(1, 4):
        try:
            raw_start = start
            if raw_last is not None and not overwrite:
                raw_start_dt = raw_last + pd.Timedelta(days=1)
                start_dt = pd.to_datetime(start)
                raw_start = max(start_dt, raw_start_dt).strftime("%Y%m%d")

            factor_start = start
            if factor_last is not None and not overwrite:
                factor_start_dt = factor_last + pd.Timedelta(days=1)
                start_dt = pd.to_datetime(start)
                factor_start = max(start_dt, factor_start_dt).strftime("%Y%m%d")

            raw_new = pd.DataFrame()
            factor_new = pd.DataFrame()
            if overwrite or raw_last is None or pd.to_datetime(raw_start) <= end_dt:
                raw_new = _get_raw_kline_tushare(code, raw_start, end, api)
            if overwrite or factor_last is None or pd.to_datetime(factor_start) <= end_dt:
                factor_new = _get_adj_factor_tushare(code, factor_start, end, api)

            if raw_existing.empty or overwrite:
                raw_merged = raw_new
            else:
                raw_merged = pd.concat([raw_existing, raw_new], ignore_index=True)

            if factor_existing.empty or overwrite:
                factor_merged = factor_new
            else:
                factor_merged = pd.concat([factor_existing, factor_new], ignore_index=True)

            if raw_merged.empty:
                raw_merged = pd.DataFrame(columns=["date", "open", "close", "high", "low", "volume"])
            raw_merged = validate(raw_merged)
            if factor_merged.empty:
                factor_merged = pd.DataFrame(columns=["date", "factor"])
            factor_merged = validate_factor(factor_merged)

            raw_merged.to_csv(raw_path, index=False)
            factor_merged.to_csv(factor_path, index=False)
            return code, True
        except RateLimitError as exc:
            LOGGER.error("%s attempt %d hit rate limit: %s", code, attempt, exc)
            _cool_sleep(COOLDOWN_SECS)
        except Exception as exc:
            silent_seconds = 15 * attempt
            LOGGER.warning(
                "%s attempt %d failed (%s), retrying in %d seconds",
                code,
                attempt,
                str(exc)[:80],
                silent_seconds,
            )
            time.sleep(silent_seconds)

    LOGGER.error("%s failed after 3 attempts", code)
    return code, False


def download_kline(
    stocklist: Path,
    start: str,
    end: str,
    out_dir: Path,
    workers: int = 3,
    exclude_boards: Optional[set[str]] = None,
    overwrite: bool = False,
    limit: int = 0,
    offset: int = 0,
    missing_only: bool = False,
    stale_only: bool = False,
    stale_grace_days: int = 10,
    token_file: Optional[Path] = None,
) -> dict:
    os.environ["NO_PROXY"] = "api.waditu.com,.waditu.com,waditu.com"
    os.environ["no_proxy"] = os.environ["NO_PROXY"]

    ts_token = os.environ.get("TUSHARE_TOKEN")
    if not ts_token:
        candidates = []
        if token_file:
            candidates.append(token_file)
        candidates.append(PROJECT_ROOT / "tk.csv")
        candidates.append(Path.home() / "tk.csv")
        for candidate in candidates:
            token = _load_token_from_csv(candidate)
            if token:
                ts_token = token
                break

    if not ts_token:
        raise RuntimeError("TUSHARE_TOKEN is not set and tk.csv not found")

    ts.set_token(ts_token)
    api = ts.pro_api()

    exclude_boards = exclude_boards or set()
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = out_dir / "raw_price"
    factor_dir = out_dir / "adj_factor"
    raw_dir.mkdir(parents=True, exist_ok=True)
    factor_dir.mkdir(parents=True, exist_ok=True)

    codes = load_codes_from_stocklist(stocklist, exclude_boards)
    if stale_only:
        end_dt = pd.to_datetime(end)
        grace_dt = end_dt - pd.Timedelta(days=int(stale_grace_days))
        filtered = []
        for code in codes:
            raw_path = raw_dir / f"{code}.csv"
            factor_path = factor_dir / f"{code}.csv"
            raw_last = _last_date(raw_path)
            factor_last = _last_date(factor_path)
            if raw_last is None or factor_last is None:
                filtered.append(code)
                continue
            if raw_last < grace_dt or factor_last < grace_dt:
                filtered.append(code)
        LOGGER.info(
            "Filtered %d symbols needing update (from %d, grace=%dd)",
            len(filtered),
            len(codes),
            int(stale_grace_days),
        )
        codes = filtered
    elif missing_only:
        filtered = []
        for code in codes:
            raw_path = raw_dir / f"{code}.csv"
            factor_path = factor_dir / f"{code}.csv"
            if raw_path.exists() and factor_path.exists():
                continue
            filtered.append(code)
        LOGGER.info("Filtered %d missing symbols (from %d)", len(filtered), len(codes))
        codes = filtered

    if offset > 0:
        codes = codes[offset:]
    if limit > 0:
        codes = codes[:limit]

    success_count = 0
    failed_count = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                fetch_one,
                code,
                start,
                end,
                raw_dir,
                factor_dir,
                overwrite,
                api,
            ): code
            for code in codes
        }
        for future in tqdm(as_completed(futures), total=len(futures), desc="Download"):
            code = futures[future]
            try:
                _, success = future.result()
                if success:
                    success_count += 1
                else:
                    failed_count += 1
            except Exception as exc:
                LOGGER.error("%s download error: %s", code, exc)
                failed_count += 1

    return {
        "success": success_count,
        "failed": failed_count,
        "symbols": len(codes),
        "output_dir": str(out_dir),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download daily kline data from Tushare",
    )
    parser.add_argument("--start", default="20190101", help="Start date YYYYMMDD")
    parser.add_argument("--end", default="today", help="End date YYYYMMDD or 'today'")
    parser.add_argument(
        "--adjust",
        default="none",
        choices=["qfq", "hfq", "none"],
        help="Deprecated (raw_price + adj_factor are always downloaded)",
    )
    parser.add_argument("--stocklist", type=Path, required=True)
    parser.add_argument(
        "--exclude-boards",
        nargs="*",
        default=[],
        choices=["gem", "star", "bj"],
    )
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--missing-only", action="store_true")
    parser.add_argument("--stale-only", action="store_true")
    parser.add_argument("--stale-grace-days", type=int, default=10)
    parser.add_argument("--token-file", type=Path, default=None)

    args = parser.parse_args()

    start = dt.date.today().strftime("%Y%m%d") if str(args.start).lower() == "today" else args.start
    end = dt.date.today().strftime("%Y%m%d") if str(args.end).lower() == "today" else args.end

    if args.adjust != "none":
        LOGGER.warning("--adjust is deprecated; raw_price + adj_factor are always downloaded")

    summary = download_kline(
        stocklist=args.stocklist,
        start=start,
        end=end,
        out_dir=args.out,
        workers=args.workers,
        exclude_boards=set(args.exclude_boards or []),
        overwrite=args.overwrite,
        limit=args.limit,
        offset=args.offset,
        missing_only=bool(args.missing_only),
        stale_only=bool(args.stale_only),
        stale_grace_days=int(args.stale_grace_days),
        token_file=args.token_file,
    )

    LOGGER.info("Download done: %s", summary)


if __name__ == "__main__":
    main()
