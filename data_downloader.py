"""
股票日线数据下载器 (基于 StockTradebyZ/fetch_kline.py)

从 stocklist.csv 读取股票池，使用 Tushare Pro API 批量下载日线数据。
支持前复权(qfq)、后复权(hfq)和不复权(none)三种模式。

特性:
- 自动限流检测和重试
- 多线程并发下载
- 断点续传支持 (不覆盖已存在文件)
- 板块过滤 (创业板/科创板/北交所)

使用示例:
    # 基础用法
    TUSHARE_TOKEN=your_token python data_downloader.py \\
        --stocklist stocklist.csv \\
        --start 20050101 \\
        --workers 3

    # 排除创业板和科创板
    TUSHARE_TOKEN=your_token python data_downloader.py \\
        --stocklist stocklist.csv \\
        --start 20240101 \\
        --exclude-boards gem star \\
        --workers 6
"""

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
from typing import List, Optional
import os

import pandas as pd
import tushare as ts
from tqdm import tqdm

warnings.filterwarnings("ignore")

# --------------------------- 全局配置 --------------------------- #
PROJECT_ROOT = Path(__file__).resolve().parent
LOG_FILE = PROJECT_ROOT / "download.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"),
    ],
)
logger = logging.getLogger("download_kline")

# --------------------------- 限流/封禁处理配置 --------------------------- #
COOLDOWN_SECS = 600
BAN_PATTERNS = (
    "访问频繁", "请稍后", "超过频率", "频繁访问",
    "too many requests", "429",
    "forbidden", "403",
    "max retries exceeded"
)


def _looks_like_ip_ban(exc: Exception) -> bool:
    """检测是否为限流/封禁错误"""
    msg = (str(exc) or "").lower()
    return any(pat in msg for pat in BAN_PATTERNS)


class RateLimitError(RuntimeError):
    """表示命中限流/封禁，需要长时间冷却后重试。"""
    pass


def _cool_sleep(base_seconds: int) -> None:
    """带抖动的睡眠，避免多线程同时唤醒"""
    jitter = random.uniform(0.9, 1.2)
    sleep_s = max(1, int(base_seconds * jitter))
    logger.warning("⚠️  疑似被限流/封禁，进入冷却期 %d 秒...", sleep_s)
    time.sleep(sleep_s)


# --------------------------- Tushare API 封装 --------------------------- #
pro: Optional[ts.pro_api] = None  # 模块级API会话


def set_api(session) -> None:
    """由外部注入已创建好的 ts.pro_api() 会话"""
    global pro
    pro = session


def _to_ts_code(code: str) -> str:
    """
    将6位股票代码转换为Tushare标准格式
    
    规则:
    - 60/68/9开头 -> .SH (上交所)
    - 4/8开头 -> .BJ (北交所)
    - 其他 -> .SZ (深交所)
    """
    code = str(code).zfill(6)
    if code.startswith(("60", "68", "9")):
        return f"{code}.SH"
    elif code.startswith(("4", "8")):
        return f"{code}.BJ"
    else:
        return f"{code}.SZ"


def _get_kline_tushare(
    code: str,
    start: str,
    end: str,
    adjust: str = "qfq"
) -> pd.DataFrame:
    """
    获取单只股票的K线数据
    
    关键：第91行的 None 检查非常重要！
    Tushare API 有时会返回 None 而不是空 DataFrame
    """
    ts_code = _to_ts_code(code)
    try:
        df = ts.pro_bar(
            ts_code=ts_code,
            adj=adjust,
            start_date=start,
            end_date=end,
            freq="D",
            api=pro
        )
    except Exception as e:
        if _looks_like_ip_ban(e):
            raise RateLimitError(str(e)) from e
        raise

    # ⚠️ 关键检查：API可能返回None或其他非DataFrame类型
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    
    if df.empty:
        return pd.DataFrame()

    # 标准化列名和数据类型
    df = df.rename(columns={"trade_date": "date", "vol": "volume"})[
        ["date", "open", "close", "high", "low", "volume"]
    ].copy()
    df["date"] = pd.to_datetime(df["date"])
    for c in ["open", "close", "high", "low", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def validate(df: pd.DataFrame) -> pd.DataFrame:
    """数据验证：去重、检查日期"""
    if df is None or df.empty:
        return df
    df = df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    if df["date"].isna().any():
        raise ValueError("存在缺失日期！")
    if (df["date"] > pd.Timestamp.today()).any():
        raise ValueError("数据包含未来日期，可能抓取错误！")
    return df


# --------------------------- 读取 stocklist.csv & 过滤板块 --------------------------- #

def _filter_by_boards_stocklist(
    df: pd.DataFrame,
    exclude_boards: set[str]
) -> pd.DataFrame:
    """
    根据板块过滤股票
    
    exclude_boards 可选值：
    - gem  : 创业板 300/301 (.SZ)
    - star : 科创板 688 (.SH)
    - bj   : 北交所 (.BJ 或 4/8开头)
    """
    code = df["symbol"].astype(str)
    ts_code = df["ts_code"].astype(str).str.upper()
    mask = pd.Series(True, index=df.index)

    if "gem" in exclude_boards:
        mask &= ~code.str.startswith(("300", "301"))
    if "star" in exclude_boards:
        mask &= ~code.str.startswith(("688",))
    if "bj" in exclude_boards:
        mask &= ~(ts_code.str.endswith(".BJ") | code.str.startswith(("4", "8")))

    return df[mask].copy()


def load_codes_from_stocklist(
    stocklist_csv: Path,
    exclude_boards: set[str]
) -> List[str]:
    """从 stocklist.csv 加载股票代码列表"""
    df = pd.read_csv(stocklist_csv)
    df = _filter_by_boards_stocklist(df, exclude_boards)
    codes = df["symbol"].astype(str).str.zfill(6).tolist()
    codes = list(dict.fromkeys(codes))  # 去重保持顺序
    logger.info("从 %s 读取到 %d 只股票 (排除板块: %s)",
                stocklist_csv, len(codes),
                ",".join(sorted(exclude_boards)) or "无")
    return codes


# --------------------------- 单只股票抓取 --------------------------- #

def fetch_one(
    code: str,
    start: str,
    end: str,
    out_dir: Path,
    adjust: str = "qfq",
    overwrite: bool = False,
) -> tuple[str, bool]:
    """
    抓取单只股票数据
    
    返回:
        (code, success): 股票代码和是否成功
    """
    csv_path = out_dir / f"{code}.csv"
    
    # 跳过已存在的文件（除非设置了overwrite）
    if csv_path.exists() and not overwrite:
        logger.debug("%s 文件已存在，跳过", code)
        return code, True

    for attempt in range(1, 4):
        try:
            new_df = _get_kline_tushare(code, start, end, adjust)
            if new_df.empty:
                logger.debug("%s 无数据，生成空表", code)
                new_df = pd.DataFrame(columns=["date", "open", "close", "high", "low", "volume"])
            new_df = validate(new_df)
            new_df.to_csv(csv_path, index=False)
            logger.info("✓ %s 保存成功 (%d 条记录)", code, len(new_df))
            return code, True
        except RateLimitError as e:
            logger.error("✗ %s 第 %d 次抓取疑似被封禁: %s", code, attempt, e)
            _cool_sleep(COOLDOWN_SECS)
        except Exception as e:
            silent_seconds = 15 * attempt
            logger.warning("⚠ %s 第 %d 次抓取失败 (%s)，%d 秒后重试",
                         code, attempt, str(e)[:50], silent_seconds)
            time.sleep(silent_seconds)
    
    logger.error("✗ %s 三次抓取均失败，已跳过！", code)
    return code, False


# --------------------------- 主入口 --------------------------- #

def main():
    parser = argparse.ArgumentParser(
        description="从 stocklist.csv 读取股票池并用 Tushare 抓取日线K线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基础用法 (前复权，3个线程)
  python download_kline.py --stocklist stocklist.csv --start 20050101 --workers 3

  # 排除创业板和科创板
  python download_kline.py --stocklist stocklist.csv --start 20050101 \\
      --exclude-boards gem star --workers 3

  # 后复权，覆盖已有文件
  python download_kline.py --stocklist stocklist.csv --start 20050101 \\
      --adjust hfq --overwrite --workers 2
        """
    )
    
    # 数据范围
    parser.add_argument("--start", default="20190101",
                       help="起始日期 YYYYMMDD (默认: 20190101)")
    parser.add_argument("--end", default="today",
                       help="结束日期 YYYYMMDD 或 'today' (默认: today)")
    
    # 复权模式
    parser.add_argument("--adjust", default="qfq",
                       choices=["qfq", "hfq", "none"],
                       help="复权模式: qfq=前复权, hfq=后复权, none=不复权 (默认: qfq)")
    
    # 股票清单与板块过滤
    parser.add_argument("--stocklist", type=Path, required=True,
                       help="股票清单CSV路径 (需含 ts_code 或 symbol 列)")
    parser.add_argument("--exclude-boards", nargs="*", default=[],
                       choices=["gem", "star", "bj"],
                       help="排除板块: gem(创业板300/301) star(科创板688) bj(北交所)")
    
    # 输出设置
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "data",
                       help="输出目录 (默认: ./data)")
    parser.add_argument("--overwrite", action="store_true",
                       help="覆盖已存在的文件 (默认: 跳过)")
    
    # 性能设置
    parser.add_argument("--workers", type=int, default=3,
                       help="并发线程数 (默认: 3，建议根据账户权限调整)")
    parser.add_argument("--limit", type=int, default=0,
                       help="限制下载数量 (0=全部，用于测试)")
    
    args = parser.parse_args()

    # ---------- Tushare Token ---------- #
    os.environ["NO_PROXY"] = "api.waditu.com,.waditu.com,waditu.com"
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    
    ts_token = os.environ.get("TUSHARE_TOKEN")
    if not ts_token:
        logger.error("❌ 未设置 TUSHARE_TOKEN 环境变量")
        logger.error("请运行: export TUSHARE_TOKEN=你的token")
        sys.exit(1)
    
    ts.set_token(ts_token)
    global pro
    pro = ts.pro_api()
    logger.info("✓ Tushare token 已设置")

    # ---------- 日期解析 ---------- #
    start = dt.date.today().strftime("%Y%m%d") if str(args.start).lower() == "today" else args.start
    end = dt.date.today().strftime("%Y%m%d") if str(args.end).lower() == "today" else args.end

    # ---------- 输出目录 ---------- #
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("✓ 输出目录: %s", out_dir.resolve())

    # ---------- 从 stocklist.csv 读取股票池 ---------- #
    if not args.stocklist.exists():
        logger.error("❌ 股票清单文件不存在: %s", args.stocklist)
        sys.exit(1)
    
    exclude_boards = set(args.exclude_boards or [])
    codes = load_codes_from_stocklist(args.stocklist, exclude_boards)

    if not codes:
        logger.error("❌ stocklist 为空或被过滤后无代码，请检查")
        sys.exit(1)
    
    if args.limit > 0:
        codes = codes[:args.limit]
        logger.info("⚠️  限制下载数量: %d", args.limit)

    logger.info("=" * 70)
    logger.info("开始下载任务")
    logger.info("  股票数量: %d", len(codes))
    logger.info("  日期范围: %s → %s", start, end)
    logger.info("  复权模式: %s", args.adjust)
    logger.info("  并发线程: %d", args.workers)
    logger.info("  排除板块: %s", ",".join(sorted(exclude_boards)) or "无")
    logger.info("=" * 70)

    # ---------- 多线程抓取 ---------- #
    success_count = 0
    failed_count = 0
    
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                fetch_one,
                code,
                start,
                end,
                out_dir,
                args.adjust,
                args.overwrite,
            ): code
            for code in codes
        }
        
        for future in tqdm(as_completed(futures), total=len(futures), desc="下载进度"):
            code = futures[future]
            try:
                _, success = future.result()
                if success:
                    success_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                logger.error("✗ %s 下载出错: %s", code, e)
                failed_count += 1

    # ---------- 结果统计 ---------- #
    logger.info("=" * 70)
    logger.info("下载任务完成")
    logger.info("  成功: %d", success_count)
    logger.info("  失败: %d", failed_count)
    logger.info("  数据保存至: %s", out_dir.resolve())
    logger.info("  日志文件: %s", LOG_FILE.resolve())
    logger.info("=" * 70)


if __name__ == "__main__":
    main()

