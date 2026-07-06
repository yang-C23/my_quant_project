#!/usr/bin/env python
"""Generate (or verify) golden CSVs from the v1 backtrader reference indicators.

Usage:
    python tests/fixtures/generate_goldens.py           # (re)write goldens/
    python tests/fixtures/generate_goldens.py --check   # verify reproducibility

Goldens record the v1 bt_legacy behavior verbatim, including its warmup
quirks (bt seeds recursions with 0.0 during leading-NaN warmup; classic
EMA seeding). They are the parity anchor for TASK-020/021/024 tests.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import backtrader as bt
import numpy as np
import pandas as pd

FIXTURES = Path(__file__).resolve().parent
GOLDENS = FIXTURES / "goldens"
SYMBOLS = ["sh600000", "sz000001"]

sys.path.insert(0, str(FIXTURES.parent / "reference"))

from bt_legacy.brick import BrickIndicator, TDXSMA  # noqa: E402
from bt_legacy.dual_trend import DualTrend  # noqa: E402
from bt_legacy.kdj_tdx import KDJTDX  # noqa: E402
from bt_legacy.volume_breath import VolumeBreath  # noqa: E402

from quant.etl.staging import parse_day_bytes  # noqa: E402


class _Recorder(bt.Strategy):
    """Attach all reference indicators and record every line from bar 1."""

    def __init__(self) -> None:
        self.sma_3_1 = TDXSMA(self.data.close, period=3, m=1)
        self.sma_40_4 = TDXSMA(self.data.close, period=40, m=4)
        self.kdj = KDJTDX(self.data)
        self.dual = DualTrend(self.data)
        self.breath = VolumeBreath(self.data)
        self.brick = BrickIndicator(self.data)
        self.rows: list[dict] = []

    def prenext(self) -> None:  # record warmup bars too (NaN where undefined)
        self.next()

    def next(self) -> None:
        self.rows.append(
            {
                "date": self.data.datetime.date(0).isoformat(),
                "sma_3_1": self.sma_3_1.sma[0],
                "sma_40_4": self.sma_40_4.sma[0],
                "k": self.kdj.k[0],
                "d": self.kdj.d[0],
                "j": self.kdj.j[0],
                "short_trend": self.dual.short_trend[0],
                "long_trend": self.dual.long_trend[0],
                "avghigh": self.breath.avghigh[0],
                "avglow": self.breath.avglow[0],
                "activity": self.breath.activity[0],
                "brick": self.brick.brick[0],
                "brick_xg": self.brick.xg[0],
            }
        )


def _load_feed(symbol: str) -> bt.feeds.PandasData:
    buf = (FIXTURES / "tdx" / "lday" / f"{symbol}.day").read_bytes()
    df = parse_day_bytes(buf, symbol)
    df = df.assign(datetime=pd.to_datetime(df["date"])).set_index("datetime")
    return bt.feeds.PandasData(dataname=df, openinterest=-1)


def generate(symbol: str) -> pd.DataFrame:
    cerebro = bt.Cerebro(runonce=False)
    cerebro.adddata(_load_feed(symbol))
    cerebro.addstrategy(_Recorder)
    (strat,) = cerebro.run()
    return pd.DataFrame(strat.rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify goldens reproduce")
    args = parser.parse_args()

    GOLDENS.mkdir(exist_ok=True)
    failures = 0
    for symbol in SYMBOLS:
        frame = generate(symbol)
        out = GOLDENS / f"bt_legacy_{symbol}.csv"
        if args.check:
            committed = pd.read_csv(out)
            same = committed.shape == frame.shape and bool(
                np.allclose(
                    committed.drop(columns="date").to_numpy(float),
                    frame.drop(columns="date").to_numpy(float),
                    rtol=1e-12,
                    atol=1e-12,
                    equal_nan=True,
                )
                and (committed["date"] == frame["date"]).all()
            )
            print(f"{out.name}: {'OK' if same else 'MISMATCH'} ({len(frame)} rows)")
            failures += 0 if same else 1
        else:
            frame.to_csv(out, index=False)
            print(f"wrote {out.name} ({len(frame)} rows)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
