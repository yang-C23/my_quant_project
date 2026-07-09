"""Backtrader A-share data feed with tradability flags."""

from __future__ import annotations

import pandas as pd
import backtrader as bt

from quant.data.api import get_ohlcv

_PRICE_COLUMNS = ("open", "high", "low", "close")
_FLAG_MISSING = -1.0


class AShareDataFeed(bt.feeds.PandasData):
    """Pandas feed exposing raw tradability inputs alongside qfq OHLCV.

    Flag lines use ``0.0`` for false, ``1.0`` for true, and ``-1.0`` for
    missing source data. Raw prices and limit prices remain NaN when absent;
    constraints treat a missing raw open as non-tradable rather than infer a
    price limit from the adjusted prices.
    """

    lines = ("is_suspended", "limit_up_price", "limit_down_price", "raw_open")
    params = (
        ("datetime", None),
        ("open", "open"),
        ("high", "high"),
        ("low", "low"),
        ("close", "close"),
        ("volume", "volume"),
        ("openinterest", None),
        ("is_suspended", "is_suspended"),
        ("limit_up_price", "limit_up_price"),
        ("limit_down_price", "limit_down_price"),
        ("raw_open", "raw_open"),
    )


def _prepare_feed_frame(qfq: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    frame = qfq.copy()
    frame.index = pd.to_datetime(frame.index)
    frame = frame.sort_index()

    raw_frame = raw.rename(columns={"open": "raw_open", "suspended": "is_suspended"}).copy()
    raw_frame.index = pd.to_datetime(raw_frame.index)
    frame = frame.join(
        raw_frame[["raw_open", "is_suspended", "limit_up_price", "limit_down_price"]], how="left"
    )

    # Keep suspension dates in the feed. Adjusted prices carry forward across
    # those bars; leading gaps remain NaN and volume/amount cannot imply trades.
    for column in _PRICE_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").ffill()
    for column in ("volume", "amount"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)

    frame["is_suspended"] = pd.to_numeric(frame["is_suspended"], errors="coerce").where(
        lambda values: values.notna(), _FLAG_MISSING
    )
    for column in ("raw_open", "limit_up_price", "limit_down_price"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def build_feed(symbol: str, start: str | None, end: str | None) -> AShareDataFeed:
    """Load a qfq feed plus raw A-share tradability flags for one symbol.

    Trading-calendar bars are preserved, including suspended bars. qfq OHLC
    values are forward-filled only across later missing values, while a leading
    missing price remains NaN. Missing volume/amount becomes zero. ``raw_open``
    and ``limit_*_price`` intentionally remain NaN, and the suspension line
    uses ``-1`` as its explicit missing-data sentinel.
    """
    qfq = get_ohlcv(
        symbol,
        start=start,
        end=end,
        adjust="qfq",
        fields=("open", "high", "low", "close", "volume", "amount"),
    )
    raw = get_ohlcv(
        symbol,
        start=start,
        end=end,
        adjust="raw",
        fields=("open", "suspended", "limit_up_price", "limit_down_price"),
    )
    frame = _prepare_feed_frame(qfq, raw)
    feed = AShareDataFeed(dataname=frame)
    feed._name = symbol
    feed.plotinfo.plot = False
    return feed
